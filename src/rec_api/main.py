import re
import secrets
import hmac
from datetime import date, datetime, timedelta, timezone
from pathlib import Path as FsPath
from typing import Annotated, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.orm import Session

from rec_normalizers import (
    EVENT_KINDS,
    parse_pool_schedule,
    Connect2Counts,
    ParseError,
    Zone,
    parse_connect2_counts,
    detect_page_type,
    parse_vems_events,
)

from .config import Settings, settings_from_env
from .mailer import Mailer, default_mailer
from .reports import digest, summarize
from .db import (
    ActivitySnapshot,
    Base,
    EventBatch,
    EventRow,
    Facility,
    LoginCode,
    Report,
    UserSession,
    make_engine,
)
from .schemas import (
    FACILITY_ID_PATTERN,
    ActivityOut,
    CodeRequestIn,
    CodeRequestOut,
    FacilityIn,
    FacilityOut,
    IngestActivityIn,
    EventOut,
    IngestActivityOut,
    IngestEventsIn,
    IngestEventsOut,
    IngestIn,
    IngestOut,
    ReportIn,
    ReportOut,
    VerifyIn,
    VerifyOut,
)

_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    404: "not_found",
    409: "conflict",
    422: "invalid_input",
    429: "rate_limited",
}

FacilityId = Annotated[str, Path(pattern=FACILITY_ID_PATTERN)]

DISPLAY_TZ = ZoneInfo("America/Los_Angeles")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    mailer: Mailer | None = None,
) -> FastAPI:
    settings = settings or Settings()
    now = clock or (lambda: datetime.now(timezone.utc))
    mailer = mailer or default_mailer(settings)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    # Databases made before facilities had venues need the new column.
    if "venues" not in {c["name"] for c in inspect(engine).get_columns("facilities")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE facilities ADD COLUMN venues JSON"))

    app = FastAPI(
        title="UCLA Rec Transparency API",
        version="0.1.0",
        description="Normalized facility, event and activity data for UCLA Recreation.",
    )

    # --- shared pieces -----------------------------------------------------

    def get_session():
        with Session(engine) as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def error_body(code: str, message: str, details=None) -> dict:
        body = {"error": {"code": code, "message": message}}
        if details is not None:
            body["error"]["details"] = details
        return body

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        code = _ERROR_CODES.get(exc.status_code, "error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"where": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body("invalid_input", "the request did not match the schema", details),
            status_code=422,
        )

    def get_facility_or_404(session: Session, facility_id: str) -> Facility:
        facility = session.get(Facility, facility_id)
        if facility is None:
            raise HTTPException(404, f"no facility with id {facility_id!r}")
        return facility

    def official_for(session: Session, facility_id: str) -> dict | None:
        snapshot = session.scalars(
            select(ActivitySnapshot)
            .where(ActivitySnapshot.facility_id == facility_id)
            .order_by(ActivitySnapshot.received_at.desc(), ActivitySnapshot.id.desc())
            .limit(1)
        ).first()
        if snapshot is None:
            return None
        counts = Connect2Counts(
            facility_name=None,
            as_of=snapshot.as_of,
            zones=[Zone(**z) for z in snapshot.zones],
        )
        return counts.to_official(
            now=now(), stale_after_minutes=settings.stale_after_minutes
        )

    def reported_for(session: Session, facility_id: str) -> dict | None:
        since = now() - timedelta(minutes=settings.report_window_minutes)
        rows = session.execute(
            select(Report.user_hash, Report.level, Report.created_at)
            .where(Report.facility_id == facility_id, Report.created_at >= since)
            .order_by(Report.created_at, Report.id)
        ).all()
        latest: dict[str, tuple[int, datetime]] = {}
        for user, level, created in rows:  # one voice per person: newest wins
            latest[user] = (level, created)
        return summarize(list(latest.values()), settings.report_window_minutes)

    def facility_out(f: Facility) -> FacilityOut:
        return FacilityOut(
            id=f.id, name=f.name, type=f.type, venues=f.venues or [], updated_at=_iso(f.updated_at)
        )

    # --- routes ------------------------------------------------------------

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/facilities", response_model=list[FacilityOut])
    def list_facilities(session: SessionDep):
        rows = session.scalars(select(Facility).order_by(Facility.id)).all()
        return [facility_out(f) for f in rows]

    @app.get("/v1/facilities/{facility_id}", response_model=FacilityOut)
    def get_facility(facility_id: FacilityId, session: SessionDep):
        return facility_out(get_facility_or_404(session, facility_id))

    @app.put("/v1/facilities/{facility_id}", response_model=FacilityOut)
    def put_facility(facility_id: FacilityId, body: FacilityIn, session: SessionDep):
        facility = session.get(Facility, facility_id)
        if facility is None:
            facility = Facility(
                id=facility_id, name=body.name, type=body.type, venues=body.venues, updated_at=now()
            )
            session.add(facility)
        else:
            facility.name, facility.type, facility.venues = body.name, body.type, body.venues
            facility.updated_at = now()
        session.commit()
        return facility_out(facility)

    def store_activity(
        session: Session, *, facility_id: str, source_id: str, content: str,
        content_type: str, source_timezone: str,
    ) -> IngestOut:
        get_facility_or_404(session, facility_id)
        try:
            counts = parse_connect2_counts(content, source_tz=source_timezone)
        except ParseError as exc:
            raise HTTPException(422, f"could not read the page: {exc}") from exc
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(422, f"unknown time zone {source_timezone!r}") from exc

        session.add(
            ActivitySnapshot(
                facility_id=facility_id,
                source_id=source_id,
                received_at=now(),
                as_of=counts.as_of,
                zones=[z.model_dump(mode="json") for z in counts.zones],
                content_type=content_type,
                raw_content=content,
            )
        )
        session.commit()
        return IngestOut(
            status="published",
            type="connect2_counts",
            source_id=source_id,
            facility_id=facility_id,
            zones=len(counts.zones),
            as_of=_iso(counts.as_of),
        )

    @app.post("/v1/ingest/activity", response_model=IngestActivityOut, status_code=201)
    def ingest_activity(body: IngestActivityIn, session: SessionDep):
        out = store_activity(
            session, facility_id=body.facility_id, source_id=body.source_id,
            content=body.content, content_type=body.content_type,
            source_timezone=body.source_timezone,
        )
        return IngestActivityOut(
            status="published", facility_id=body.facility_id, source_id=body.source_id,
            zones=out.zones, as_of=out.as_of,
        )

    @app.get("/v1/facilities/{facility_id}/activity", response_model=ActivityOut)
    def get_activity(facility_id: FacilityId, session: SessionDep):
        get_facility_or_404(session, facility_id)
        return ActivityOut(
            facility_id=facility_id,
            official=official_for(session, facility_id),
            reported=reported_for(session, facility_id),
        )

    @app.get("/v1/activity", response_model=list[ActivityOut])
    def list_activity(session: SessionDep):
        ids = session.scalars(select(Facility.id).order_by(Facility.id)).all()
        return [
            ActivityOut(
                facility_id=i,
                official=official_for(session, i),
                reported=reported_for(session, i),
            )
            for i in ids
        ]

    # --- sign-in and community reports -------------------------------------

    def normalize_email(raw: str) -> str:
        email = raw.strip().lower()
        domain = email.rpartition("@")[2]
        if not re.fullmatch(r"[^@\s]+@[a-z0-9.-]+", email) or (
            domain not in settings.allowed_email_domains
        ):
            allowed = " or ".join(f"@{d}" for d in settings.allowed_email_domains)
            raise HTTPException(422, f"use your UCLA email address ({allowed})")
        return email

    @app.post("/v1/auth/code", response_model=CodeRequestOut, status_code=202)
    def request_code(body: CodeRequestIn, session: SessionDep):
        email = normalize_email(body.email)
        eh = digest(settings.secret, "email:" + email)
        t = now()
        recent = session.scalars(
            select(LoginCode)
            .where(LoginCode.email_hash == eh)
            .order_by(LoginCode.created_at.desc())
            .limit(1)
        ).first()
        if recent and t - recent.created_at < timedelta(seconds=settings.code_resend_seconds):
            raise HTTPException(429, "a code was just sent: wait a minute before asking again")
        session.execute(delete(LoginCode).where(LoginCode.email_hash == eh))
        code = f"{secrets.randbelow(1_000_000):06d}"
        session.add(
            LoginCode(
                email_hash=eh,
                code_hash=digest(settings.secret, f"code:{eh}:{code}"),
                created_at=t,
                expires_at=t + timedelta(minutes=settings.code_ttl_minutes),
            )
        )
        session.commit()
        mailer.send_code(email, code)
        return CodeRequestOut(
            status="sent",
            expires_in_seconds=settings.code_ttl_minutes * 60,
            dev_code=code if settings.show_codes else None,
        )

    @app.post("/v1/auth/verify", response_model=VerifyOut)
    def verify_code(body: VerifyIn, session: SessionDep):
        email = normalize_email(body.email)
        eh = digest(settings.secret, "email:" + email)
        t = now()
        row = session.scalars(
            select(LoginCode)
            .where(LoginCode.email_hash == eh)
            .order_by(LoginCode.created_at.desc())
            .limit(1)
        ).first()
        if row is None or row.expires_at < t:
            raise HTTPException(422, "that code has expired: ask for a new one")
        if row.attempts >= settings.code_max_attempts:
            raise HTTPException(422, "too many wrong tries: ask for a new code")
        expected = digest(settings.secret, f"code:{eh}:{body.code.strip()}")
        if not hmac.compare_digest(expected, row.code_hash):
            row.attempts += 1
            session.commit()
            raise HTTPException(422, "that code is not right")
        session.delete(row)
        token = secrets.token_urlsafe(32)
        expires = t + timedelta(days=settings.session_days)
        session.add(
            UserSession(
                token_hash=digest(settings.secret, "token:" + token),
                user_hash=digest(settings.secret, "user:" + email),
                created_at=t,
                expires_at=expires,
            )
        )
        session.commit()
        return VerifyOut(token=token, expires_at=_iso(expires))

    def current_user(
        session: SessionDep, authorization: Annotated[str | None, Header()] = None
    ) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "sign in with your UCLA email first")
        row = session.get(UserSession, digest(settings.secret, "token:" + token.strip()))
        if row is None or row.expires_at < now():
            raise HTTPException(401, "your sign-in has expired: sign in again")
        return row.user_hash

    @app.post(
        "/v1/facilities/{facility_id}/reports", response_model=ReportOut, status_code=201
    )
    def add_report(
        facility_id: FacilityId,
        body: ReportIn,
        session: SessionDep,
        user: Annotated[str, Depends(current_user)],
    ):
        get_facility_or_404(session, facility_id)
        session.add(
            Report(facility_id=facility_id, user_hash=user, level=body.level, created_at=now())
        )
        session.commit()
        return ReportOut(
            status="recorded",
            facility_id=facility_id,
            level=body.level,
            reported=reported_for(session, facility_id),
        )

    # --- events ------------------------------------------------------------

    def event_out(e: EventRow) -> EventOut:
        return EventOut(
            id=e.id,
            name=e.name,
            kind=e.kind,
            status="cancelled" if e.cancelled else "scheduled",
            start=_iso(e.start_at),
            end=_iso(e.end_at),
            all_day=e.all_day,
            location=e.location,
            venue=e.venue,
            space=e.space,
            facility_id=e.facility_id,
            source_id=e.source_id,
        )

    def store_events(
        session: Session, *, source_id: str, content: str, content_type: str,
        event_date: date, source_timezone: str, facility_id: str | None,
    ) -> IngestOut:
        if facility_id is not None:
            get_facility_or_404(session, facility_id)
        try:
            parsed = parse_vems_events(content, event_date, source_tz=source_timezone)
        except ParseError as exc:
            raise HTTPException(422, f"could not read the page: {exc}") from exc
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(422, f"unknown time zone {source_timezone!r}") from exc

        day = event_date.isoformat()
        # venue code (lower case) -> facility id, from what each facility declared
        owner = {
            v.strip().lower(): f.id
            for f in session.scalars(select(Facility)).all()
            for v in (f.venues or [])
        }

        # Re-scraping a source and date replaces what it published before.
        old_batches = session.scalars(
            select(EventBatch.id).where(
                EventBatch.source_id == source_id, EventBatch.event_date == day
            )
        ).all()
        replaced = 0
        if old_batches:
            replaced = session.execute(
                delete(EventRow).where(EventRow.batch_id.in_(old_batches))
            ).rowcount
            session.execute(delete(EventBatch).where(EventBatch.id.in_(old_batches)))

        batch = EventBatch(
            source_id=source_id, event_date=day, received_at=now(),
            content_type=content_type, raw_content=content,
        )
        session.add(batch)
        session.flush()
        by_kind: dict[str, int] = {}
        by_facility: dict[str, int] = {}
        for e in parsed:
            fid = facility_id or owner.get((e.venue or "").lower())
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            by_facility[fid or "unassigned"] = by_facility.get(fid or "unassigned", 0) + 1
            session.add(
                EventRow(
                    batch_id=batch.id, source_id=source_id, event_date=day,
                    name=e.name, kind=e.kind, start_at=e.start, end_at=e.end,
                    all_day=e.all_day, cancelled=e.cancelled, location=e.location,
                    venue=e.venue, space=e.space, facility_id=fid,
                )
            )
        session.commit()
        return IngestOut(
            status="published", type="events", source_id=source_id,
            facility_id=facility_id, event_date=day, events=len(parsed),
            replaced=replaced, by_kind=by_kind, by_facility=by_facility,
        )

    def store_pool_schedule(
        session: Session, *, source_id: str, content: str, content_type: str,
        source_timezone: str, facility_id: str | None,
    ) -> IngestOut:
        if facility_id is not None:
            get_facility_or_404(session, facility_id)
        try:
            parsed, skipped = parse_pool_schedule(content, source_tz=source_timezone)
            zone = ZoneInfo(source_timezone)
        except ParseError as exc:
            raise HTTPException(422, f"could not read the pool calendar: {exc}") from exc
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(422, f"unknown time zone {source_timezone!r}") from exc

        owner = {
            v.strip().lower(): f.id
            for f in session.scalars(select(Facility)).all()
            for v in (f.venues or [])
        }
        days = [e.start.astimezone(zone).date().isoformat() for e in parsed]
        # The calendar covers many days and is reissued whole: replace everything
        # this source published before.
        old = session.scalars(select(EventBatch.id).where(EventBatch.source_id == source_id)).all()
        replaced = 0
        if old:
            replaced = session.execute(delete(EventRow).where(EventRow.batch_id.in_(old))).rowcount
            session.execute(delete(EventBatch).where(EventBatch.id.in_(old)))
        batch = EventBatch(
            source_id=source_id, event_date=min(days), received_at=now(),
            content_type=content_type, raw_content=content,
        )
        session.add(batch)
        session.flush()
        by_kind: dict[str, int] = {}
        by_facility: dict[str, int] = {}
        for e, day in zip(parsed, days):
            fid = facility_id or owner.get((e.venue or "").lower())
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            by_facility[fid or "unassigned"] = by_facility.get(fid or "unassigned", 0) + 1
            session.add(
                EventRow(
                    batch_id=batch.id, source_id=source_id, event_date=day,
                    name=e.name, kind=e.kind, start_at=e.start, end_at=e.end,
                    all_day=e.all_day, cancelled=False, location=e.location,
                    venue=e.venue, space=e.space, facility_id=fid,
                )
            )
        session.commit()
        return IngestOut(
            status="published", type="pool_schedule", source_id=source_id,
            facility_id=facility_id, event_date=min(days), last_date=max(days),
            events=len(parsed), replaced=replaced, by_kind=by_kind,
            by_facility=by_facility, skipped=skipped[:20] or None,
        )

    @app.post("/v1/ingest/events", response_model=IngestEventsOut, status_code=201)
    def ingest_events(body: IngestEventsIn, session: SessionDep):
        out = store_events(
            session, source_id=body.source_id, content=body.content,
            content_type=body.content_type, event_date=body.event_date,
            source_timezone=body.source_timezone, facility_id=None,
        )
        return IngestEventsOut(
            status="published", source_id=body.source_id, event_date=out.event_date,
            events=out.events, replaced=out.replaced, by_kind=out.by_kind,
        )

    # --- the one endpoint for every source ---------------------------------

    @app.post("/v1/ingest", response_model=IngestOut, status_code=201)
    def ingest(body: IngestIn, session: SessionDep):
        page_type = detect_page_type(body.content)
        if page_type is None:
            raise HTTPException(
                422,
                "could not tell what this is: expected a rendered Connect2 counts "
                "page, a rendered Browse Events page or a pool calendar PDF",
            )
        if page_type == "pool_schedule":
            return store_pool_schedule(
                session, source_id=body.source_id, content=body.content,
                content_type=body.content_type, source_timezone=body.source_timezone,
                facility_id=body.facility_id,
            )
        if page_type == "connect2_counts":
            if body.facility_id is None:
                raise HTTPException(
                    422, "facility_id is required for a Connect2 counts page"
                )
            return store_activity(
                session, facility_id=body.facility_id, source_id=body.source_id,
                content=body.content, content_type=body.content_type,
                source_timezone=body.source_timezone,
            )
        try:
            zone = ZoneInfo(body.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(422, f"unknown time zone {body.source_timezone!r}") from exc
        return store_events(
            session, source_id=body.source_id, content=body.content,
            content_type=body.content_type,
            event_date=body.event_date or now().astimezone(zone).date(),
            source_timezone=body.source_timezone, facility_id=body.facility_id,
        )

    @app.get("/v1/events", response_model=list[EventOut])
    def list_events(
        session: SessionDep,
        on: Annotated[date | None, Query(alias="date")] = None,
        date_from: Annotated[
            date | None, Query(alias="from", description="first day of a range; use with `to`")
        ] = None,
        date_to: Annotated[date | None, Query(alias="to", description="last day of a range")] = None,
        facility_id: Annotated[str | None, Query(pattern=FACILITY_ID_PATTERN)] = None,
        venue: str | None = None,
        kind: Annotated[str | None, Query(description="comma-separated kinds")] = None,
        include_cancelled: bool = False,
        upcoming: Annotated[
            bool, Query(description="events not yet over, on any day; ignores date and from/to")
        ] = False,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        if upcoming:
            query = select(EventRow).where(EventRow.end_at >= now())
        elif date_from or date_to:
            if not (date_from and date_to) or date_to < date_from:
                raise HTTPException(422, "give both `from` and `to`, with `to` on or after `from`")
            query = select(EventRow).where(
                EventRow.event_date >= date_from.isoformat(), EventRow.event_date <= date_to.isoformat()
            )
        else:
            day = (on or now().astimezone(DISPLAY_TZ).date()).isoformat()
            query = select(EventRow).where(EventRow.event_date == day)
        if facility_id:
            query = query.where(EventRow.facility_id == facility_id)
        if venue:
            query = query.where(func.lower(EventRow.venue) == venue.lower())
        if kind:
            kinds = [k.strip() for k in kind.split(",") if k.strip()]
            unknown = [k for k in kinds if k not in EVENT_KINDS]
            if unknown:
                raise HTTPException(
                    422, f"unknown kind {unknown[0]!r}; use one of {', '.join(EVENT_KINDS)}"
                )
            query = query.where(EventRow.kind.in_(kinds))
        if not include_cancelled:
            query = query.where(EventRow.cancelled.is_(False))
        rows = session.scalars(
            query.order_by(EventRow.start_at, EventRow.name, EventRow.id).limit(limit)
        ).all()
        return [event_out(e) for e in rows]

    # --- the dashboard -----------------------------------------------------
    # Last, so every /v1 route and /docs wins over a file of the same name.
    web = FsPath(__file__).parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    return app


def create_app_from_env() -> FastAPI:
    """For: uvicorn --factory rec_api.main:create_app_from_env"""
    return create_app(settings_from_env())
