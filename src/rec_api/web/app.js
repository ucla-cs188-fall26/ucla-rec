/* UCLA Rec Live: plain JavaScript, no build step, no outside libraries. */
(() => {
  "use strict";

  const TZ = "America/Los_Angeles";
  // Order of the facility list. Anything not named here goes after, A to Z.
  const ORDER = ["wooden-center", "bfit", "hitch-courts", "sunset-rec", "pools"];
  const REFRESH_MS = 60_000;
  const LEVELS = { 1: ["Quiet", "low"], 2: ["Moderate", "mid"], 3: ["Busy", "high"] };

  // How each kind of booking is shown. `closure` kinds are the ones that
  // take a space away from drop-in use.
  const KINDS = {
    maintenance: { label: "Closed: maintenance", cls: "bad", closure: true },
    athletics: { label: "Reserved: athletics", cls: "warn", closure: true },
    club_sport: { label: "Reserved: club", cls: "warn", closure: true },
    other: { label: "Reserved", cls: "warn", closure: true },
    class: { label: "Class", cls: "info", closure: false },
    open_recreation: { label: "Open rec", cls: "ok", closure: false },
    // from the pool calendar
    closed: { label: "Closed", cls: "bad", closure: true },
    pool_hours: { label: "Open", cls: "ok", closure: false },
    pool_activity: { label: "Pool activity", cls: "info", closure: false },
    tbd: { label: "Hours not posted", cls: "info", closure: false },
  };
  // The right-hand panel has two lists. Closures and reservations are what limits use
  // what limits use; hours of availability are when a place is open. Both show one day.
  const FEED_KINDS = "class,club_sport,athletics,maintenance,other,closed";
  const AVAIL_KINDS = "open_recreation,pool_hours,tbd";
  const CALENDAR_KINDS = "pool_hours,pool_activity,tbd,closed";
  const laToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date());
  // Calendar days are plain dates ("2026-11-12"); do the arithmetic at noon UTC so no clock change can shift a day.
  const ymd = (d) => d.toISOString().slice(0, 10);
  const parseYmd = (k) => new Date(k + "T12:00:00Z");
  const addDays = (k, n) => ymd(new Date(parseYmd(k).getTime() + n * 864e5));
  const selectedDay = () => state.day || laToday();
  const mondayOf = (k) => addDays(k, -((parseYmd(k).getUTCDay() + 6) % 7));

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // ---- small storage helpers (storage can be blocked, so never trust it) ----
  const memory = {};
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v == null ? (memory[key] ?? fallback) : JSON.parse(v); }
      catch { return memory[key] ?? fallback; }
    },
    set(key, value) {
      memory[key] = value;
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* keep the in-memory copy */ }
    },
    del(key) { delete memory[key]; try { localStorage.removeItem(key); } catch { /* ignore */ } },
  };

  // ---- talking to the API ----------------------------------------------------
  const token = () => {
    const t = store.get("rec.token", null);
    if (t && new Date(t.expires_at) > new Date()) return t.token;
    store.del("rec.token");
    return null;
  };

  async function api(path, { method = "GET", body, auth = false } = {}) {
    if (window.recDemoApi) return window.recDemoApi(method, path, body, auth ? token() : null);
    const headers = {};
    if (body) headers["Content-Type"] = "application/json";
    if (auth && token()) headers.Authorization = "Bearer " + token();
    let res;
    try {
      res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    } catch {
      throw Object.assign(new Error("Can't reach the server. Check your connection."), { status: 0 });
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw Object.assign(new Error(data?.error?.message || "Something went wrong."), { status: res.status });
    return data;
  }

  // ---- time helpers ----------------------------------------------------------
  const fmtTime = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  const fmtDay = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });
  const dayKey = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d); // 2026-11-12
  const time = (iso) => fmtTime.format(new Date(iso)).replace(" AM", " AM").replace(/^0/, "");
  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    const h = Math.round(mins / 60);
    return h < 24 ? h + " h ago" : Math.round(h / 24) + " d ago";
  }
  function dayLabel(d) {
    const today = dayKey(new Date()), key = dayKey(d);
    if (key === today) return "Today";
    if (key === dayKey(new Date(Date.now() + 864e5))) return "Tomorrow";
    return fmtDay.format(d);
  }

  // ---- state -----------------------------------------------------------------
  const state = {
    facilities: [], activity: {}, current: null,
    view: "official",          // which segment is showing on the activity card
    evFilter: "closures",      // or "hours"
    evVenue: null,             // pools: show one pool only
    day: null,                 // the day the right-hand lists show; null means today
    events: [], hours: [], calendar: [], modal: null, lastHtml: {},
  };

  const views = () => store.get("rec.views", {});
  function recordView(id) {
    const v = views();
    v[id] = { n: (v[id]?.n || 0) + 1, last: Date.now() };
    store.set("rec.views", v);
  }
  // Most viewed first; ties go to the one opened most recently.
  function topFacility() {
    const v = views();
    const known = state.facilities.filter((f) => v[f.id]);
    if (known.length) {
      known.sort((a, b) => v[b.id].n - v[a.id].n || v[b.id].last - v[a.id].last);
      return { id: known[0].id, fromHistory: true };
    }
    return { id: state.facilities[0]?.id, fromHistory: false };
  }

  function sortFacilities(list) {
    const rank = (id) => { const i = ORDER.indexOf(id); return i < 0 ? 99 : i; };
    return [...list].sort((a, b) => rank(a.id) - rank(b.id) || a.name.localeCompare(b.name));
  }

  // ---- routing ---------------------------------------------------------------
  function route() {
    const m = location.hash.match(/^#f-([a-z0-9-]+)$/);
    return m ? { page: "facility", id: m[1] } : { page: "home" };
  }

  async function show() {
    const r = route();
    let id, home = false, fromHistory = false;
    if (r.page === "home") {
      const top = topFacility();
      id = top.id; home = true; fromHistory = top.fromHistory;
    } else {
      id = r.id;
      if (!state.facilities.some((f) => f.id === id)) { renderMissing(); return; }
      if (state.shownVisit !== location.hash) { recordView(id); state.shownVisit = location.hash; }
    }
    if (state.current !== id) { state.view = null; state.evVenue = null; state.evFilter = "closures"; }
    state.current = id; state.home = home; state.fromHistory = fromHistory;
    renderNav();
    await refresh();
  }

  async function refresh() {
    const id = state.current;
    if (!id) return;
    try {
      const week = mondayOf(laToday());
      const day = selectedDay();
      const [activity, events, hours, calendar] = await Promise.all([
        api(`/v1/facilities/${id}/activity`),
        api(`/v1/events?facility_id=${id}&date=${day}&limit=500&kind=${FEED_KINDS}`),
        api(`/v1/events?facility_id=${id}&date=${day}&limit=500&kind=${AVAIL_KINDS}`).catch(() => []),
        api(`/v1/events?facility_id=${id}&from=${week}&to=${addDays(week, 140)}&limit=500&kind=${CALENDAR_KINDS}`).catch(() => []),
      ]);
      if (id !== state.current) return;
      state.activity[id] = activity; state.events = events; state.hours = hours; state.calendar = calendar; state.error = null;
    } catch (e) { state.error = e.message; }
    renderMain(); renderEvents();
    loadNavStatus();
  }

  // ---- facility list ---------------------------------------------------------
  function summaryOf(a) {
    if (!a) return { cls: "", text: "" };
    const zones = (a.official?.zones || []).filter((z) => z.open && z.percent_full != null);
    if (zones.length && !a.official.stale) {
      const top = zones.reduce((x, y) => (y.percent_full > x.percent_full ? y : x));
      return { cls: top.band === "medium" ? "mid" : top.band === "high" ? "high" : top.band === "low" ? "low" : "",
               text: `Busiest zone ${Math.round(top.percent_full)}%` };
    }
    if (a.reported) { const [label, cls] = LEVELS[a.reported.level]; return { cls, text: label + " (reported)" }; }
    return { cls: "", text: "No recent data" };
  }

  function renderNav() {
    const rows = state.facilities.map((f) => {
      const s = summaryOf(state.activity[f.id]);
      const here = f.id === state.current;
      return `<a href="#f-${esc(f.id)}" ${here ? 'aria-current="page"' : ""}>
        <span class="n-name">${esc(f.name)}</span>
        <span class="n-sub"><span class="dot ${s.cls}"></span>${esc(s.text || " ")}</span></a>`;
    });
    $("#nav").innerHTML = `<h2>Facilities</h2>${rows.join("")}`;
  }

  async function loadNavStatus() {
    try {
      const all = await api("/v1/activity");
      for (const a of all) state.activity[a.facility_id] = a;
      renderNav();
    } catch { /* the list still works without status dots */ }
  }

  // ---- centre: activity ------------------------------------------------------
  function fillClass(band) { return band === "low" ? "low" : band === "medium" ? "mid" : band === "high" ? "high" : ""; }

  function officialHtml(o) {
    const mins = Math.round((Date.now() - new Date(o.as_of)) / 60000);
    const rows = o.zones.map((z) => {
      if (!z.open) {
        return `<div class="zone closed"><div class="z-name">${esc(z.name)}<small>Closed</small></div>
          <div class="track" aria-hidden="true"></div><div class="z-val">Closed</div></div>`;
      }
      const pct = z.percent_full == null ? null : Math.min(100, Math.round(z.percent_full));
      return `<div class="zone"><div class="z-name">${esc(z.name)}
          <small>${z.capacity ? `${z.count} of ${z.capacity} people` : `${z.count} people`}</small></div>
        <div class="track" role="img" aria-label="${esc(z.name)} ${pct == null ? "" : pct + " percent full"}">
          <div class="fill ${fillClass(z.band)}" style="width:${pct ?? 0}%"></div></div>
        <div class="z-val">${pct == null ? "<b>" + z.count + "</b>" : `<b>${pct}%</b> <small>full</small>`}</div></div>`;
    }).join("");
    const stale = o.stale
      ? `<span class="pill warn">Out of date: no update from UCLA in ${mins >= 120 ? Math.round(mins / 60) + " h" : mins + " min"}</span>`
      : `<span class="pill ok">Live</span>`;
    return `<div class="asof">${stale}<span>Counts as of ${time(o.as_of)} PT (${ago(o.as_of)})</span></div>
      <div class="zones ${o.stale ? "stale" : ""}">${rows}</div>
      <div class="legend"><span><i class="dot low"></i>Low</span><span><i class="dot mid"></i>Medium</span><span><i class="dot high"></i>High</span>
        <span>Darker means busier. Percent full is the count divided by capacity.</span></div>`;
  }

  function reportedHtml(r, hasOfficial) {
    const meter = [1, 2, 3].map((n) =>
      `<div class="${r && r.level === n ? "on " + LEVELS[n][1] : ""}">${LEVELS[n][0]}</div>`).join("");
    const head = r
      ? `<div class="big-label">${LEVELS[r.level][0]}</div>
         <p class="report-meta">${r.reports} ${r.reports === 1 ? "report" : "reports"} in the last ${r.window_minutes} minutes
         · latest ${ago(r.as_of)}${r.score !== r.level ? ` · leaning ${r.score < r.level ? "quieter" : "busier"}` : ""}</p>`
      : `<div class="big-label none">No reports yet</div>
         <p class="report-meta">Nobody has reported in the last 45 minutes.</p>`;
    const why = hasOfficial ? "" : `<div class="note">UCLA doesn't publish live counts for this place, so this is the main source.</div>`;
    return `${head}<div class="meter" role="img" aria-label="${r ? "Reported level: " + LEVELS[r.level][0] : "No reports"}">${meter}</div>
      <button class="btn" id="report-btn">Report how busy it is</button>
      <p class="report-meta" style="margin-top:10px">Reports come from UCLA students and staff. Several are combined, so one person can't skew it.</p>${why}`;
  }

  function renderMain() {
    const f = state.facilities.find((x) => x.id === state.current);
    const a = state.activity[state.current];
    if (!f) return;
    const hasOfficial = !!a?.official;
    if (!state.view || (state.view === "official" && !hasOfficial)) state.view = hasOfficial ? "official" : "reported";

    const sub = state.home
      ? (state.fromHistory ? `<span class="badge">Your most viewed</span>` : "")
      : "";
    const hello = state.home && !state.fromHistory
      ? `<p>Choose a facility from the list. The one you open most will appear here next time.</p>` : `<p>${esc(typeLabel(f.type))}</p>`;
    const toggle = hasOfficial
      ? `<div class="seg" role="group" aria-label="Activity source">
           <button aria-pressed="${state.view === "official"}" data-view="official">UCLA live counts</button>
           <button aria-pressed="${state.view === "reported"}" data-view="reported">Community reports</button></div>`
      : "";
    const body = state.error && !a ? `<div class="err">${esc(state.error)}</div>`
      : !a ? `<p class="empty">Loading…</p>`
      : state.view === "official" ? officialHtml(a.official) : reportedHtml(a.reported, hasOfficial);
    const heading = state.view === "official" ? "Activity level: UCLA live counts" : "Activity level: community reports";

    html("#main", `<div class="page-head"><h1>${esc(f.name)}${sub}</h1>${hello}</div>
      ${calendarHtml()}<section class="card activity"><div class="activity-top"><h2>${heading}</h2>${toggle}</div>${body}</section>`);
    document.title = `${f.name} · UCLA Recreation`;
  }

  // The pool calendar, laid out like UCLA's printed one: weeks of Monday to Sunday,
  // each day listing every pool's hours, with activities indented under their pool.
  const clock = (iso, short) => {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit", hour12: true }).formatToParts(new Date(iso));
    const g = (t) => parts.find((p) => p.type === t)?.value || "";
    const m = g("minute") === "00" ? "" : ":" + g("minute"), ap = g("dayPeriod").toLowerCase();
    return g("hour") + m + (short ? ap[0] : ap);
  };
  const span = (e, short) => `${clock(e.start, short)}-${clock(e.end, short)}`;

  function dayLines(items) {
    // Banner: the same closure on several pools ("Thanksgiving holiday: all pools closed").
    const closed = items.filter((e) => e.kind === "closed");
    if (closed.length > 1 && closed.every((e) => e.name === closed[0].name) && /all pools/i.test(closed[0].name) && closed.length === items.length) {
      return `<div class="cal-banner">${esc(closed[0].name.replace(/\s*closed$/i, ""))}<br>Closed</div>`;
    }
    const out = [];
    for (let i = 0; i < items.length; i++) {
      const e = items[i], code = esc(e.space || e.venue || "");
      if (e.kind === "pool_hours") {
        const ranges = [span(e)];
        while (items[i + 1]?.kind === "pool_hours" && items[i + 1].venue === e.venue) ranges.push(span(items[++i]));
        out.push(`<div class="cal-line">${code} - ${ranges.map((r) => `<span class="nw">${esc(r)}</span>`).join(", ")}</div>`);
      } else if (e.kind === "pool_activity") {
        out.push(`<div class="cal-act">${esc(e.name)} <span class="nw">${esc(span(e, true))}</span></div>`);
      } else if (e.kind === "closed") {
        out.push(`<div class="cal-line cal-closed">${code} - ${esc(e.name.replace(/^Closed/i, "CLOSED"))}</div>`);
      } else if (e.kind === "tbd") {
        out.push(`<div class="cal-line">${code} - TBD</div>`);
      }
    }
    return out.join("");
  }

  function calendarHtml() {
    if (!state.calendar.length) return "";
    const byDay = {};
    for (const e of [...state.calendar].sort((a, b) => a.id - b.id)) (byDay[dayKey(new Date(e.start))] ||= []).push(e);
    const keys = Object.keys(byDay).sort();
    const today = laToday(), first = mondayOf(keys[0] < today ? today : keys[0]), last = keys[keys.length - 1];
    if (last < first) return "";
    const weeks = [];
    for (let w = first; w <= last; w = addDays(w, 7)) weeks.push(w);

    const names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    const month = (k, o) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...o }).format(parseYmd(k));
    const m1 = month(first, { month: "long" }), m2 = month(addDays(weeks[weeks.length - 1], 6), { month: "long", year: "numeric" });
    const title = m1 === m2.split(" ")[0] ? m2 : `${m1}\u2013${m2}`;

    // Key: "PP - Park Pool", from what the calendar itself says.
    const seen = new Map();
    for (const e of state.calendar) if (e.space && e.venue && e.space !== e.venue && !seen.has(e.space)) seen.set(e.space, e.venue);
    const key = [...seen].map(([c, v]) => `<span>${esc(c)} - ${esc(v)}</span>`).join("");

    const cells = weeks.map((w) => names.map((nm, i) => {
      const k = addDays(w, i), items = byDay[k] || [];
      const num = parseYmd(k).getUTCDate() === 1 ? `${month(k, { month: "short" })} 1` : String(parseYmd(k).getUTCDate());
      const cls = ["cal-cell", items.some((e) => e.kind === "closed") ? "closed" : "", k === today ? "today" : "", items.length ? "" : "empty"].join(" ");
      return `<div class="${cls}"><div class="cal-num"><span class="d-name">${nm.slice(0, 3)}</span>${esc(num)}</div>${dayLines(items)}</div>`;
    }).join("")).join("");

    return `<section class="card cal">
      <div class="activity-top"><h2>Pool hours: ${esc(title)}</h2></div>
      <div class="cal-key">${key}</div>
      <div class="cal-grid" role="group" aria-label="Pool hours by day">
        ${names.map((n) => `<div class="cal-dow">${n}</div>`).join("")}${cells}
      </div>
      <p class="legend">From UCLA Recreation's posted pool calendar. Times can change with staffing. Highlighted days have a closure.</p>
    </section>`;
  }

  function typeLabel(t) {
    return ({ gym: "Gym", fitness_center: "Fitness center", pool: "Pools", court: "Courts", field: "Fields", other: "Facility" })[t] || "Facility";
  }

  // Only touch the page when the markup changed, so scrolling and focus survive refreshes.
  function html(sel, markup) {
    if (state.lastHtml[sel] === markup) return;
    state.lastHtml[sel] = markup;
    $(sel).innerHTML = markup;
  }

  // ---- right: events -----------------------------------------------------------
  function renderEvents() {
    const f = state.facilities.find((x) => x.id === state.current);
    if (!f) return;
    const hoursTab = state.evFilter === "hours";
    const day = selectedDay(), isToday = day === laToday();
    const named = dayLabel(parseYmd(day));
    const label = isToday ? "today" : named === "Tomorrow" ? "tomorrow" : named;
    const venues = [...new Set([...state.events, ...state.hours].map((e) => e.venue).filter(Boolean))].sort();
    const showVenueFilter = venues.length > 1 && f.type === "pool";
    let list = (hoursTab ? state.hours : state.events).filter((e) => e.status !== "cancelled");
    if (showVenueFilter && state.evVenue) list = list.filter((e) => e.venue === state.evVenue);

    const body = list.length
      ? list.map((e) => eventHtml(e, venues.length > 1, { hours: hoursTab, today: isToday })).join("")
      : `<p class="empty">${hoursTab ? "No opening hours" : "No closures or reservations"} listed for ${esc(label)}.
         The lists only have days UCLA's calendar has been collected for.</p>`;

    const chips = showVenueFilter
      ? `<div class="chips"><button class="chip" data-venue="" aria-pressed="${!state.evVenue}">All pools</button>` +
        venues.map((v) => `<button class="chip" data-venue="${esc(v)}" aria-pressed="${state.evVenue === v}">${esc(v)}</button>`).join("") + `</div>`
      : "";
    html("#events", `<div class="card ev-card">
      <div class="ev-head"><h2>${hoursTab ? "Hours of availability" : "Closures &amp; reservations"}</h2>
        <p>${hoursTab ? `When ${esc(f.name)} is open` : `At ${esc(f.name)}`}, ${esc(label)}, from UCLA's reservation calendar</p></div>
      <div class="daynav" role="group" aria-label="Choose a day">
        <button data-day="-1" aria-label="Previous day">&lsaquo;</button>
        <input type="date" id="day-input" value="${esc(day)}" aria-label="Date to show">
        <button data-day="1" aria-label="Next day">&rsaquo;</button>
        ${isToday ? "" : `<button class="chip" data-day="today">Back to today</button>`}
      </div>
      <div class="ev-filters">
        <div class="seg small" role="group" aria-label="Which list">
          <button data-evf="closures" aria-pressed="${!hoursTab}">Closures &amp; reservations</button>
          <button data-evf="hours" aria-pressed="${hoursTab}">Hours of availability</button></div>${chips}</div>
      <div class="ev-list">${body}</div></div>`);
  }

  async function setDay(k) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(k || "")) return;
    state.day = k === laToday() ? null : k;
    renderEvents();
    const id = state.current;
    try {
      const day = selectedDay();
      const [events, hours] = await Promise.all([
        api(`/v1/events?facility_id=${id}&date=${day}&limit=500&kind=${FEED_KINDS}`),
        api(`/v1/events?facility_id=${id}&date=${day}&limit=500&kind=${AVAIL_KINDS}`).catch(() => []),
      ]);
      if (id !== state.current || day !== selectedDay()) return;
      state.events = events; state.hours = hours;
    } catch { state.events = []; state.hours = []; }
    renderEvents();
  }

  function eventHtml(e, multiVenue, o = {}) {
    const k = KINDS[e.kind] || KINDS.other;
    const start = new Date(e.start), end = new Date(e.end), now = Date.now();
    const range = e.all_day ? "All day"
      : e.end === e.start ? time(e.start)
      : `${time(e.start)} – ${time(e.end)}`;
    const live = !e.all_day && start <= now && end >= now;
    const place = e.space || e.location || e.venue || "Location not listed";
    const headline = e.kind === "closed" && e.venue ? esc(e.venue)
      : multiVenue && e.venue && e.space ? `${esc(e.venue)} · ${esc(e.space)}` : esc(place);
    // Today's entries stay listed after they end; say so.
    const over = o.today && !e.all_day && end < now;
    const badge = live ? `<small>${o.hours ? "Open now" : "Happening now"}</small>` : over ? `<small class="past">Ended</small>` : "";
    return `<div class="ev ${live ? "now" : ""}">
      <div class="t">${esc(range)}${badge}</div>
      <div><div class="where">${headline}</div><div class="what">${esc(e.name)}</div>
      <span class="pill ${k.cls}">${esc(k.label)}</span></div></div>`;
  }

  // ---- report flow (UCLA email, code, then Quiet / Moderate / Busy) --------------
  function openReport() {
    state.modal = { step: token() ? "level" : "email", email: "", error: "", hint: "", busy: false, level: null };
    renderModal();
  }
  function closeModal() { state.modal = null; $("#modal-root").innerHTML = ""; }

  function renderModal() {
    const m = state.modal;
    if (!m) return;
    const f = state.facilities.find((x) => x.id === state.current);
    const err = m.error ? `<div class="err" role="alert">${esc(m.error)}</div>` : "";
    const hint = m.hint ? `<div class="hint">${esc(m.hint)}</div>` : "";
    let inner = "";
    if (m.step === "email") {
      inner = `<h2>Sign in to report</h2><p class="sub">Use your UCLA email so only the UCLA community can report. We'll send a 6-digit code. Your email is not stored.</p>
        <form id="f-email"><label for="email">UCLA email</label>
        <input id="email" type="email" inputmode="email" autocomplete="email" placeholder="bruin@g.ucla.edu" value="${esc(m.email)}" required>
        ${err}<div class="row"><button type="button" class="btn ghost" data-close>Cancel</button>
        <button class="btn" ${m.busy ? "disabled" : ""}>Send code</button></div></form>`;
    } else if (m.step === "code") {
      inner = `<h2>Enter your code</h2><p class="sub">We sent a 6-digit code to ${esc(m.email)}. It expires in 10 minutes.</p>
        <form id="f-code"><label for="code">Code</label>
        <input id="code" class="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" required>
        ${hint}${err}<div class="row"><button type="button" class="btn ghost" data-back>Back</button>
        <button class="btn" ${m.busy ? "disabled" : ""}>Verify</button></div></form>`;
    } else {
      inner = `<h2>How busy is ${esc(f?.name || "it")} right now?</h2><p class="sub">Pick what you see. You can update it later.</p>
        <div class="choices" role="group" aria-label="How busy">${[1, 2, 3].map((n) =>
          `<button class="${LEVELS[n][1]}" data-level="${n}" aria-pressed="${m.level === n}">${LEVELS[n][0]}</button>`).join("")}</div>
        ${err}<div class="row"><button type="button" class="btn ghost" data-close>Cancel</button>
        <button class="btn" id="submit-level" ${m.level && !m.busy ? "" : "disabled"}>Send report</button></div>`;
    }
    $("#modal-root").innerHTML = `<div class="scrim" data-close-scrim><div class="modal" role="dialog" aria-modal="true">${inner}</div></div>`;
    const focus = $("#modal-root input") || $("#modal-root .choices button");
    if (focus) focus.focus();
  }

  async function modalSubmit(kind) {
    const m = state.modal;
    // Read the boxes before redrawing: the redraw replaces them.
    if (kind === "email") m.email = $("#email").value.trim();
    const typedCode = kind === "code" ? $("#code").value.trim() : "";
    m.error = ""; m.busy = true; renderModal();
    try {
      if (kind === "email") {
        const r = await api("/v1/auth/code", { method: "POST", body: { email: m.email } });
        m.step = "code";
        m.hint = r.dev_code ? `Test mode: your code is ${r.dev_code}` : "";
      } else if (kind === "code") {
        const r = await api("/v1/auth/verify", { method: "POST", body: { email: m.email, code: typedCode } });
        store.set("rec.token", r); m.step = "level";
      } else {
        await api(`/v1/facilities/${state.current}/reports`, { method: "POST", auth: true, body: { level: m.level } });
        closeModal(); toast("Thanks. Your report is in."); state.view = "reported"; await refresh(); return;
      }
    } catch (e) {
      if (e.status === 401) { store.del("rec.token"); m.step = "email"; m.error = "Please sign in again."; }
      else m.error = e.message;
    }
    m.busy = false; renderModal();
  }

  function toast(text) {
    const t = document.createElement("div");
    t.className = "toast"; t.textContent = text; t.setAttribute("role", "status");
    document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
  }

  function renderMissing() {
    state.current = null;
    renderNav();
    html("#main", `<div class="card activity"><h2>We couldn't find that facility</h2><p class="report-meta">Pick one from the list.</p></div>`);
    html("#events", "");
  }

  document.addEventListener("change", (e) => { if (e.target.id === "day-input") setDay(e.target.value); });

  // ---- events from the page ----------------------------------------------------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button,[data-close-scrim]");
    if (!t) return;
    if (t.dataset.view) { state.view = t.dataset.view; renderMain(); }
    else if (t.dataset.day !== undefined) {
      const cur = selectedDay();
      setDay(t.dataset.day === "today" ? laToday() : addDays(cur, +t.dataset.day));
    }
    else if (t.dataset.evf) { state.evFilter = t.dataset.evf; renderEvents(); }
    else if (t.dataset.venue !== undefined && t.classList.contains("chip")) { state.evVenue = t.dataset.venue || null; renderEvents(); }
    else if (t.id === "report-btn") openReport();
    else if (t.dataset.level) { state.modal.level = +t.dataset.level; renderModal(); }
    else if (t.id === "submit-level") modalSubmit("level");
    else if (t.hasAttribute("data-back")) { state.modal.step = "email"; state.modal.error = ""; renderModal(); }
    else if (t.hasAttribute("data-close")) closeModal();
    else if (t.hasAttribute("data-close-scrim") && e.target === t) closeModal();
  });
  document.addEventListener("submit", (e) => {
    e.preventDefault();
    if (e.target.id === "f-email") modalSubmit("email");
    if (e.target.id === "f-code") modalSubmit("code");
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.modal) closeModal(); });
  window.addEventListener("hashchange", () => { if (!state.modal) show(); });

  // ---- start ---------------------------------------------------------------------
  function loadScript(src) {
    return new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => fail(new Error("could not load " + src));
      document.head.appendChild(s);
    });
  }

  async function boot() {
    const wantsDemo = new URLSearchParams(location.search).has("demo");
    if (wantsDemo && !window.recDemoApi) await loadScript("demo.js");
    if (window.recDemoApi) $("#demo-banner").hidden = false;
    try {
      state.facilities = sortFacilities(await api("/v1/facilities"));
    } catch (e) {
      html("#main", `<div class="err">${esc(e.message)}</div>`); return;
    }
    if (!state.facilities.length) {
      html("#main", `<div class="card activity"><h2>No facilities yet</h2>
        <p class="report-meta">Add facilities and run the scraper (see the README), then reload.</p></div>`);
      return;
    }
    await show();
    setInterval(() => { if (!state.modal && !document.hidden) refresh(); }, REFRESH_MS);
  }
  boot();
})();