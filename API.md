# ucla-rec-api

An API that gathers UCLA Recreation data into one consistent, queryable source.
Today it covers **live activity counts** (how busy each zone of a facility is).
Hours, events, intramurals, pool schedules and user-reported activity are
planned but not built yet.

## What is in this folder

| Folder | What it does |
| --- | --- |
| `src/rec_api` | The API service (FastAPI + SQLite). Stores data and serves it |
| `src/rec_scrapers` | Loads a live Connect2 counts page in a browser and can send it to the API |
| `src/rec_normalizers` | Parser that turns a rendered Connect2 counts page into clean zone records |
| `tests/` | 61 tests, with a saved Wooden page as the sample |

How the pieces fit: the scraper loads the page, the API parses and stores it,
and anyone can then read the result from the API.

## Set up (Windows PowerShell)

```powershell
cd "path\to\ucla-rec-api"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Windows: if you see "No time zone found", run: pip install tzdata
```

The scraper needs a browser. Either use the Edge browser already on Windows
(add `--browser-channel msedge` to scraper commands) or run
`python -m playwright install chromium`.

Run the tests with `python -m pytest -q`. The browser tests look for an
installed Google Chrome and skip themselves if it is not found.

## Run the API

```powershell
python -m uvicorn --factory rec_api.main:create_app_from_env --port 8000
```

- Interactive docs, where you can try every call: http://localhost:8000/docs
- Data is saved in `rec.db` in the folder you start the API from.
- Settings (environment variables):

| Variable | Meaning | Default |
| --- | --- | --- |
| `REC_DATABASE_URL` | Where data is stored | `sqlite:///./rec.db` |
| `REC_REPORT_WINDOW_MINUTES` | How long a community report counts | `45` |
| `REC_SHOW_CODES` | `1` to show the sign-in code in the API response and on the page. Testing only | off |
| `REC_SMTP_HOST`, `REC_SMTP_PORT`, `REC_SMTP_USER`, `REC_SMTP_PASSWORD`, `REC_SMTP_FROM` | Email server for sign-in codes. Without a host, codes print in the API window | none |
| `REC_STALE_AFTER_MINUTES` | How old the newest count can be before `stale` turns true | `30` |

---

## Quick start: get live data on the dashboard

```powershell
# window 1: the API and dashboard
python -m uvicorn --factory rec_api.main:create_app_from_env --port 8000

# window 2: fetch the data (needs: copy sources.example.json to sources.json,
# and set the Connect2 links; see "Scrape everything with one command")
$env:CONNECT2_WOODEN_URL = "<the Connect2 link>"
rec-run --config sources.json --browser-channel msedge
```

Then open http://localhost:8000/. Run `rec-run` again whenever you want fresh
numbers. To look around without any data, open http://localhost:8000/?demo=1.

## Run it with Docker

Two containers: `api` (the API and dashboard) and `scraper` (re-runs `rec-run`
every 5 minutes with its own headless Chromium). Data is kept in a Docker volume.

```powershell
# 1. put your links in sources.json (see "Scrape everything with one command")
# 2. start both
docker compose up --build
```

Open http://localhost:8000/. Change how often it scrapes with
`SCRAPE_EVERY_SECONDS`. Sign-in codes print in `docker compose logs api` unless
you set the `REC_SMTP_*` lines in `docker-compose.yml`. The project folder is mounted
read-only into the scraper, not baked into the image, so your access keys stay out
of it and a new `pool-schedule.pdf` is picked up on the next pass.
Stop with `docker compose down` (add `-v` to also delete the data).

---

## The dashboard

Start the API and open **http://localhost:8000/**. The API serves the dashboard
itself, so there is nothing else to install or run.

- **Home** shows the facility you open most (counted in your own browser; there
  is no login). If you haven't opened any yet, it shows the first facility.
- **One page per facility.** The list on the left comes from the facilities
  you created, so adding a facility adds a page.
- **Middle: activity level.** Facilities with UCLA live counts show a switch
  between **UCLA live counts** (a bar per zone) and **Community reports**.
  Facilities with no live counts (Hitch courts, pools) show community reports
  only.
- **Right: two lists for one day**, from UCLA's reservation calendar. The day is
  today unless you pick another with the date box or the arrows; "Back to today"
  returns. **Closures & reservations** is everything that limits use (closures,
  reservations, classes, club and athletics bookings, maintenance). **Hours of
  availability** is when a place is open (open recreation, pool hours). For
  today, an entry stays listed after it ends, marked "Ended". Days the scraper
  has not collected yet show as empty. The pools page can be narrowed to one pool.
- **Preview without an API:** open `/?demo=1` to see sample data.

The dashboard needs the five facilities to exist. `sources.example.json` creates
them (`wooden-center`, `bfit`, `hitch-courts`, `sunset-rec`, `pools`), so
copy it to `sources.json` and run the runner once (see "Scrape everything").

### Sending a community report

Click **Report how busy it is**, enter your `@ucla.edu` or `@g.ucla.edu`
address, type the 6-digit code you are sent, then pick Quiet, Moderate or Busy.
You stay signed in for 30 days in that browser.

Until you set up email, codes are printed in the window where the API runs.
To see them on the page while testing, start the API with `REC_SHOW_CODES=1`.

---

# API reference

All paths start with `/v1`. Requests and responses are JSON. Times are UTC in
ISO 8601 form (for example `2026-11-12T01:31:00Z`).

## Access

Reading is open to everyone. Writing data (facilities, scraped pages) has no
authentication, so anyone who can reach the server can change it: run it locally
or behind your own network controls. The one exception is **community reports**,
which need a signed-in UCLA email (below).

## Summary

| Method and path | What it does |
| --- | --- |
| `GET /v1/health` | Says whether the service is up |
| `GET /v1/facilities` | Lists all facilities |
| `GET /v1/facilities/{id}` | Returns one facility |
| `PUT /v1/facilities/{id}` | Creates a facility, or updates its name and type |
| `POST /v1/ingest/activity` | Takes a rendered counts page, parses it and stores the zone counts |
| `GET /v1/facilities/{id}/activity` | Returns the latest zone counts for one facility |
| `GET /v1/activity` | Returns the latest zone counts for every facility |
| `POST /v1/ingest` | **The one call for every source.** Takes any rendered page, works out whether it is a counts page or an events page, and stores it |
| `POST /v1/ingest/events` | Takes the rendered Browse Events page, parses it and stores that day's events |
| `GET /v1/events` | Lists a day's events, or the upcoming ones, with filters |
| `POST /v1/auth/code` | Emails a 6-digit sign-in code to a UCLA address |
| `POST /v1/auth/verify` | Swaps the code for a sign-in token |
| `POST /v1/facilities/{id}/reports` | Sends a community report (Quiet, Moderate or Busy). Needs the token |

A facility `id` is a short lowercase slug such as `wooden-center` or `bfit`:
letters, digits and hyphens, starting with a letter or digit.

## GET /v1/health

Checks the service is running.

```json
{ "status": "ok" }
```

## GET /v1/facilities

Returns every facility you have created, sorted by id.

```json
[
  {
    "id": "wooden-center",
    "name": "John Wooden Center",
    "type": "gym",
    "venues": ["JWC"],
    "updated_at": "2026-11-12T01:41:00Z"
  }
]
```

## GET /v1/facilities/{id}

Returns one facility, in the same shape as above. Unknown id gives a `404`.

## PUT /v1/facilities/{id}

Creates the facility, or replaces its name and type if it already exists. You
must create a facility before you can send it activity data.

Body:

| Field | Required | Notes |
| --- | --- | --- |
| `name` | Yes | Display name, 1 to 200 characters |
| `type` | No | One of `gym`, `fitness_center`, `pool`, `court`, `field`, `other` (default `other`) |
| `venues` | No | Venue codes that start this facility's event locations, for example `["JWC"]`. Events at these venues are linked to the facility |

PowerShell:

```powershell
Invoke-RestMethod -Method Put -Uri http://localhost:8000/v1/facilities/wooden-center `
  -ContentType "application/json" `
  -Body '{"name":"John Wooden Center","type":"gym"}'
```

Returns the facility (`200`).

## POST /v1/ingest

The one call for every source. Send the rendered HTML of any supported page
and the API works out what it is:

| Page | How it is recognised | What is stored |
| --- | --- | --- |
| Connect2 "Live Facility Counts" | has the `#chartContainer` | Zone counts for one facility |
| UCLA Rec "Browse Events" | has the events grid | That day's events, split across facilities by venue |
| Pool calendar PDF | JSON of the PDF's positioned words (`"format": "pdf_words"`), made by the scraper | Every day on the calendar: open hours, activities, closures. Replaces the whole earlier calendar from the same `source_id` |
| Anything else | | `422`, nothing stored |

Body:

| Field | Required | Notes |
| --- | --- | --- |
| `source_id` | Yes | Label for where the page came from |
| `content` | Yes | The rendered HTML (or, for a pool calendar, the words JSON), up to 5 MB |
| `content_type` | No | `text/html` (default), or `application/json` for a pool calendar |
| `facility_id` | Counts pages: yes | Which facility the counts belong to. For an events page it is optional: give it to put every event on that facility, leave it out to split by venue |
| `event_date` | No | Events pages: the day the page showed, `YYYY-MM-DD` (default: today in Los Angeles) |
| `source_timezone` | No | Zone the page prints times in (default `America/Los_Angeles`) |

Returns `201`. The `type` field says what it was treated as, and the rest
depends on it:

```json
{ "status": "published", "type": "connect2_counts", "source_id": "connect2-wooden",
  "facility_id": "wooden-center", "zones": 8, "as_of": "2026-11-12T01:31:00Z" }
```

```json
{ "status": "published", "type": "events", "source_id": "ucla-reserve-events",
  "event_date": "2026-11-12", "events": 50, "replaced": 0,
  "by_kind": { "athletics": 16, "club_sport": 11, "open_recreation": 9,
               "maintenance": 7, "other": 4, "class": 3 },
  "by_facility": { "wooden-center": 17, "sunset-rec": 2, "unassigned": 31 } }
```

A pool calendar returns `"type": "pool_schedule"` with the first and last day it
covers (`event_date`, `last_date`) and `skipped`, a list of any lines it could
not understand (null when everything was read).

The pool calendar adds four event kinds: `pool_hours` (an open window),
`pool_activity` (for example Open Rec Diving), `closed` (a closure, with the
reason in the name) and `tbd` (not announced yet; never guessed). Closures are
all-day. Each entry's `space` holds the short label printed on the calendar
(`PP`, `FP`, `SAC`). The Pools page draws these as a week-by-week calendar in
the same layout as UCLA's printed one, with community reports underneath, and
lists `closed` entries in the closures panel.

The two older calls below, `POST /v1/ingest/activity` and
`POST /v1/ingest/events`, still work and do the same thing for one page type.
New code should use `POST /v1/ingest`.

## POST /v1/ingest/activity

Sends a Connect2 "Live Facility Counts" page to the API. The API reads the
zones out of it, checks them, and stores them along with the original page, so
the data can be reprocessed later if the parser improves.

The scraper normally makes this call for you (see "Scrape and store" below).

Body:

| Field | Required | Notes |
| --- | --- | --- |
| `facility_id` | Yes | An existing facility |
| `source_id` | Yes | A label for where the page came from, for example `connect2-wooden` |
| `content` | Yes | The **rendered** HTML of the page (after its script has run), up to 2 MB |
| `content_type` | No | Only `text/html` is supported |
| `source_timezone` | No | Zone the page printed its "Updated" times in. Default `America/Los_Angeles` |

Returns `201`:

```json
{
  "status": "published",
  "facility_id": "wooden-center",
  "source_id": "connect2-wooden",
  "zones": 8,
  "as_of": "2026-11-12T01:31:00Z"
}
```

If the page is not readable, nothing is stored and you get a `422` with the
reason, for example when the page was saved before its script filled in the
zones.

## GET /v1/facilities/{id}/activity

Returns the most recent counts for one facility.

```json
{
  "facility_id": "wooden-center",
  "official": {
    "as_of": "2026-11-12T01:31:00Z",
    "stale": false,
    "zones": [
      {
        "zone_id": "collins-court",
        "name": "Collins Court",
        "open": true,
        "count": 35,
        "percent_full": 1.9358407079646016,
        "capacity": 1808,
        "band": "low",
        "updated_at": "2026-11-12T01:31:00Z"
      }
    ]
  },
  "reported": null
}
```

(The real response lists every zone. One is shown here.)

| Field | Meaning |
| --- | --- |
| `official` | Counts published by UCLA. `null` if nothing has been stored yet |
| `official.as_of` | When UCLA last updated any zone |
| `official.stale` | `true` when `as_of` is older than the stale limit (30 minutes by default). Worked out each time you read it, so it turns true by itself as time passes |
| `zone_id`, `name` | The zone, for example `cardio-zone` and "Cardio Zone" |
| `open` | Whether the widget lists the zone as open. Do not rely on this alone: it can still say open when the data is hours old |
| `count` | People counted at `updated_at` |
| `percent_full` | Unrounded percent of capacity. `null` when the zone is closed |
| `capacity` | Worked out as `count` divided by `percent_full`. `null` when it cannot be worked out |
| `band` | Colour of UCLA's bar: `low` (blue), `medium` (yellow), `high` (red). `null` for a colour not seen before |
| `updated_at` | When UCLA last updated this zone |
| `reported` | Reserved for user-reported activity. Always `null` for now |

There is deliberately no single "facility is X% full" number. Zones differ a lot
in size (Collins Court holds 1,808 people, Novice Circuit Zone about 20), so one
combined figure would be misleading.

## GET /v1/activity

Returns the same thing for every facility, as a list:

```json
[
  { "facility_id": "bfit", "official": null, "reported": null },
  { "facility_id": "wooden-center", "official": { "...": "as above" }, "reported": null }
]
```

## POST /v1/ingest/events

Sends the rendered UCLA Rec "Browse Events" page
(`https://reserve.recreation.ucla.edu/BrowseEvents.aspx`) to the API. The API
reads every row, works out what kind of event it is, and stores it with the
original page.

The page shows one day at a time and its rows carry only times, so you must say
which day the page was showing.

Body:

| Field | Required | Notes |
| --- | --- | --- |
| `source_id` | Yes | Label for where the page came from, for example `ucla-reserve-events` |
| `content` | Yes | The rendered HTML, up to 5 MB. The grid markup alone is enough |
| `event_date` | Yes | The day the page was showing, `YYYY-MM-DD` |
| `content_type` | No | Only `text/html` (default) |
| `source_timezone` | No | Zone the page prints times in (default `America/Los_Angeles`) |

Sending the same `source_id` and `event_date` again **replaces** what that
source published for that day, so re-scraping never creates duplicates.

Returns `201`:

```json
{
  "status": "published",
  "source_id": "ucla-reserve-events",
  "event_date": "2026-11-12",
  "events": 50,
  "replaced": 0,
  "by_kind": { "athletics": 16, "club_sport": 11, "open_recreation": 9,
               "maintenance": 7, "other": 4, "class": 3 }
}
```

A page with no events grid (a sign-in page, an unrendered page) gives a `422`
instead of being stored as "no events". A real grid with no rows is valid and
stores zero events.

## GET /v1/events

Lists one day's events, earliest first.

| Query parameter | Meaning |
| --- | --- |
| `date` | `YYYY-MM-DD`. Default: today in Los Angeles |
| `from`, `to` | A range of days, `YYYY-MM-DD`; give both. Used instead of `date` |
| `facility_id` | Only events at this facility (see "How events link to facilities") |
| `venue` | Only events at this venue, for example `JWC`, `Park Pool`. Not case sensitive |
| `kind` | One or more kinds, comma separated (list below) |
| `include_cancelled` | `true` to include cancelled events. Default: hidden |
| `upcoming` | `true` for events that are not over yet, on any day (ignores `date` and `from`/`to`) |
| `limit` | Most events to return, 1 to 500 (default 100) |

```json
[
  {
    "id": 1,
    "name": "Open Recreation Basketball",
    "kind": "open_recreation",
    "status": "scheduled",
    "start": "2026-11-12T14:30:00Z",
    "end": "2026-11-12T23:45:00Z",
    "all_day": false,
    "location": "JWC - Collins 1",
    "venue": "JWC",
    "space": "Collins 1",
    "facility_id": "wooden-center",
    "source_id": "ucla-reserve-events"
  }
]
```

Event kinds, decided from the event name:

| `kind` | Examples |
| --- | --- |
| `open_recreation` | Open Recreation, Open Recreation Basketball, Lap Swimming |
| `class` | BHIPOn-Class- Fitwell, MARTIALART-CLASS- Comp |
| `club_sport` | Club Swimming, Club Triathlon, Bruin Masters Swimming, rugby practice |
| `athletics` | Varsity practices and games (DIA ...), UCLA Cheer Squad Practice |
| `maintenance` | Custodial Cleaning, JWC Seismic Improvement Project |
| `other` | Anything not matched above |

The kind is a best guess from the name. Wrong or missing matches are fixed by
editing the rules in `src/rec_normalizers/vems_events.py`.

**Every booking is stored**, including team practices and cleaning, because
the source lists them all. Use `kind=open_recreation,class` for what a student
can show up to.

### How events link to facilities

The location text starts with a venue code (`JWC - Yates Gym` has venue `JWC`
and space `Yates Gym`). Each facility lists the venue codes it owns in its
`venues` field, so linking is data, not code:

```powershell
Invoke-RestMethod -Method Put -Uri http://localhost:8000/v1/facilities/wooden-center `
  -ContentType "application/json" `
  -Body '{"name":"John Wooden Center","type":"gym","venues":["JWC"]}'
```

When a page of events is stored, each event goes to the facility that lists its
venue (not case sensitive). Events at a venue no facility lists have
`facility_id: null`, but can still be filtered by `venue`. Adding a facility
later and re-scraping links its events.

## Community reports

Anyone with a UCLA email can report how busy a facility is. Reports are
combined into the `reported` field of the activity endpoints.

**1. Ask for a code** (`POST /v1/auth/code`), body `{"email": "bruin@g.ucla.edu"}`.
Only `@ucla.edu` and `@g.ucla.edu` are accepted. Returns `202`. A new code can
be requested once a minute. Codes expire after 10 minutes and are locked after
5 wrong tries.

**2. Verify it** (`POST /v1/auth/verify`), body `{"email": "...", "code": "123456"}`.
Returns `{"token": "...", "expires_at": "..."}`, good for 30 days.

**3. Report** (`POST /v1/facilities/{id}/reports`), with the header
`Authorization: Bearer <token>` and body `{"level": 2}` (1 Quiet, 2 Moderate,
3 Busy). Returns `201` with the updated `reported` summary. Without a valid
token it gives `401`.

How reports are combined:

- Only reports from the last 45 minutes count.
- Each person counts once: their newest report.
- The result is the middle value of those reports. With 5 or more, the lowest
  and highest are dropped first, so one outlier can't move it. Halves round up
  (a 1 and a 2 give Moderate).

```json
"reported": { "level": 2, "label": "Moderate", "score": 2.0, "reports": 4,
              "window_minutes": 45, "method": "median", "as_of": "2026-11-12T18:04:00Z" }
```

`reported` is `null` when nobody has reported in the window.

Your email is never stored. The database keeps only a keyed hash of it (to count
one person once) and a hash of the sign-in token.

## Errors

Every error has the same shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "no facility with id 'nope'"
  }
}
```

| HTTP status | `code` | When |
| --- | --- | --- |
| 401 | `unauthorized` | A report without a valid sign-in token |
| 404 | `not_found` | Unknown facility id |
| 429 | `rate_limited` | A sign-in code was requested again within a minute |
| 422 | `invalid_input` | The request did not match the rules above, or the page could not be read. Schema problems include a `details` list saying which field |

---

# Scrape everything with one command

Facilities, the venue codes they own, and the links to scrape all live in one
config file. Adding a facility or a link means editing that file, not the code.

1. Copy `sources.example.json` to `sources.json` and edit it:

```json
{
  "api": "http://localhost:8000",
  "facilities": [
    { "id": "wooden-center", "name": "John Wooden Center", "type": "gym",
      "venues": ["JWC"],
      "sources": [
        { "id": "connect2-wooden", "type": "connect2_counts", "url_env": "CONNECT2_WOODEN_URL" }
      ] }
  ],
  "sources": [
    { "id": "ucla-reserve-events", "type": "events",
      "url": "https://reserve.recreation.ucla.edu/BrowseEvents.aspx" }
  ]
}
```

   - A source under a facility belongs to that facility. A source at the top
     level (like the events page) is shared, and its events are split across
     facilities by venue.
   - `type` is `connect2_counts`, `events` or `pool_schedule`.
   - Give each link as `url` (fine for public pages), `url_env` (the name of an
     environment variable holding the link, for links that contain an access
     key), or `html_file` (a saved rendered page).
   - An `events` source with a `url` reads several days: today's page, then it
     clicks the page's "next day" arrow, and files each day under the date the
     page itself shows. `"days": 7` is the default (1 to 31); `--days N` on the
     command line overrides it, and `--date YYYY-MM-DD` reads only the page that
     is showing. Each run replaces the days it reads, so a day that changes on
     UCLA's side is updated. A run takes roughly 5 seconds per day. If the arrow
     stops working part-way, the days already read are kept and the result has a
     `warning`. The result lists each day under `days` with its event count.
   - A `pool_schedule` source reads the pool calendar PDF. Save the PDF in the
     project folder and name it with `pdf_file`:
     `{ "id": "pool-calendar", "type": "pool_schedule", "pdf_file": "pool-schedule.pdf" }`.
     Replace the file when UCLA posts a new calendar; `rec-run` reads it each
     time. (`url` also works if the link returns the PDF itself. Box sharing
     links open a viewer page, so save the file instead.) The pool codes (PP,
     FP, SAC) are read from the key printed on the calendar, so the pool names
     must be listed in the Pools facility's `venues`, for example
     `"Park Pool"`, `"Family Pool"`, `"Student Activities Center Pool"`.

2. Put the keyed links in environment variables:

```powershell
$env:CONNECT2_WOODEN_URL = "<the Connect2 link>"
```

3. Start the API, then in another window:

```powershell
rec-run --config sources.json --browser-channel msedge
```

(`rec-run` is the short name for `python -m rec_scrapers.run`; both work. It
is installed by `pip install -e .`. Browser scraping also needs
`pip install -e ".[scrape]"`.)

It creates or updates each facility, scrapes every source, and sends each page
to `POST /v1/ingest`. One source failing does not stop the others. It prints a
result for each source, and the exit code is 1 if any failed.

| Option | Meaning |
| --- | --- |
| `--config FILE` | The config file (required) |
| `--only SOURCE_ID` | Run just this source. Repeat the option for several |
| `--date YYYY-MM-DD` | Events: the day the page shows (default: today in Los Angeles) |
| `--api URL` | Use this API address instead of the one in the config |
| `--browser-channel NAME` | `msedge` or `chrome` to use an installed browser |
| `--timeout-ms N` | How long to wait for each page to fill in (default 30000) |

---

# Scrape one source at a time

The scraper loads the live page in a browser (the page fills in its numbers
with JavaScript, so a plain download would be empty), then sends it to the API.

**Window 1:** start the API as shown above.

**Window 2:**

```powershell
# create the facility once:
Invoke-RestMethod -Method Put -Uri http://localhost:8000/v1/facilities/wooden-center `
  -ContentType "application/json" `
  -Body '{"name":"John Wooden Center","type":"gym"}'

# then scrape and store (repeat this part whenever you want fresh data):
$env:CONNECT2_URL = "<the live counts link>"
python -m rec_scrapers --url-env CONNECT2_URL --browser-channel msedge `
  --post-to http://localhost:8000 --facility-id wooden-center --source-id connect2-wooden
```

Keep the link in an environment variable: it contains an access key, and the
scraper never prints it.

Scraper options:

| Option | Meaning |
| --- | --- |
| `--url-env NAME` | Read the live link from this environment variable |
| `--url LINK` | Give the link directly (it will show in your shell history) |
| `--html-file FILE` | Use a saved, already-rendered page instead of loading a link |
| `--post-to BASE_URL` | Send the page to this API. Without it, the parsed result is just printed |
| `--facility-id ID` | Which facility it belongs to (required with `--post-to`) |
| `--source-id LABEL` | Label stored with the data (default `connect2`) |
| `--browser-channel NAME` | `msedge` or `chrome` to use an installed browser |
| `--timeout-ms N` | How long to wait for the zones to appear (default 20000) |
| `--save-html FILE` | Also save the rendered page, for debugging |
| `--timezone ZONE` | Zone the page prints times in (default `America/Los_Angeles`) |

## Scrape events

The Browse Events page also loads its rows with JavaScript. With the API
running:

```powershell
python -m rec_scrapers.events_cli --browser-channel msedge `
  --post-to http://localhost:8000 --date 2026-11-12
```

`--date` must be the day the page is showing. Leave it out and it uses today
in Los Angeles, which matches the page when you first open it. Without
`--post-to` it prints the parsed events instead. `--html-file page.html` parses
a saved page with no browser.

| Option | Meaning |
| --- | --- |
| `--url LINK` | Events page (default: the UCLA Rec page) |
| `--html-file FILE` | Use a saved, rendered page |
| `--date YYYY-MM-DD` | The day the page shows (default: today in Los Angeles) |
| `--post-to BASE_URL` | Send to this API. Without it the parsed events are printed |
| `--source-id LABEL` | Label stored with the data (default `ucla-reserve-events`) |
| `--browser-channel NAME` | `msedge` or `chrome` to use an installed browser |
| `--timeout-ms N` | How long to wait for the grid (default 30000) |
| `--save-html FILE` | Also save the rendered page, for debugging |

Not yet checked against the live site: how the page switches to another day,
and whether a busy day is split over several pages of the grid. The parser is
built from a saved page of 50 events for one day.