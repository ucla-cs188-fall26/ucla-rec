# UCLA Rec dashboard

A dashboard for UCLA Recreation: how busy each facility is, today's hours and closures,
and the pool calendar, with community reports on top. It has five pages: John Wooden
Center, BFit, Hitch courts, Sunset Rec and Pools.

A small API stores the data. A scraper fills it in every few minutes from three places:

| Data | Where it comes from |
|---|---|
| How busy each area is | The Connect2 counts pages |
| Events, closures and hours | `reserve.recreation.ucla.edu/BrowseEvents.aspx`, the next 7 days |
| Pool calendar | The pool schedule PDF, saved as `pool-schedule.pdf` |

Community crowd reports need a UCLA email address to verify.

## What is in the folder

| File | What it is |
|---|---|
| `sources.json` | Your settings: facilities, venue codes and links. Contains your Connect2 key, so do not share or commit it. |
| `sources.example.json` | A blank copy to start from. |
| `pool-schedule.pdf` | The pool calendar PDF. Replace it each month. |
| `docker-compose.yml`, `Dockerfile` | For running with Docker. |
| `src/` | The code. |
| `docs/API.md` | The full API reference. |

## Before you start

1. Copy `sources.example.json` to `sources.json`.
2. In `sources.json`, replace each `PASTE-THE-CONNECT2-LINK-...` with the real Connect2 link for that facility.
3. Put the pool calendar PDF in this folder and name it exactly `pool-schedule.pdf`.

## Option 1: Docker (easiest)

Install Docker Desktop, then in this folder:

```powershell
docker compose up --build
```

Open http://localhost:8000. The first start takes a few minutes. After that the scraper
refreshes everything every 5 minutes.

| Task | Command |
|---|---|
| Run in the background | `docker compose up -d` |
| See what the scraper is doing | `docker compose logs scraper --tail 60` |
| Stop | `docker compose down` |
| Start from a blank database | `docker compose down -v` (this also deletes community reports) |

- **New PDF:** replace `pool-schedule.pdf`. The next pass picks it up, with no rebuild.
- **Changed `sources.json`:** also picked up on the next pass.
- **Changed code:** run `docker compose up --build` again.
- **Refresh interval:** set `SCRAPE_EVERY_SECONDS`, for example `$env:SCRAPE_EVERY_SECONDS=600; docker compose up -d`.

## Option 2: Python on your own machine (Windows PowerShell)

You need Python 3.11 or newer and Microsoft Edge or Chrome.

One-time setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,scrape]"
pip install tzdata
```

Every time, in two PowerShell windows (activate the `.venv` in each):

```powershell
# Window 1: the API and dashboard
uvicorn --factory rec_api.main:create_app_from_env

# Window 2: fetch the data (repeat whenever you want fresh numbers)
rec-run --config sources.json --browser-channel msedge
```

Open http://localhost:8000. Use `--browser-channel chrome` if you do not use Edge.

To scrape just one source, add `--only` with its id, for example
`rec-run --config sources.json --browser-channel msedge --only pool-calendar`.

## Reading the scraper output

Each source prints `"ok": true` or an `error`. The usual ones:

| Message | What to do |
|---|---|
| `cannot read the pool calendar PDF` | The PDF is missing or misnamed. It must be `pool-schedule.pdf`, next to `sources.json`. Windows can hide a double `.pdf.pdf`. |
| `the events grid did not fill in` | The reservation page did not load. Try again, or run once with a visible Edge or Chrome. |
| `connection refused` | The API is not running yet. |
| `0 events found` | The scraper saves what it saw in `debug-<id>.html`. Send me that file. |

## Try the dashboard without any data

Open http://localhost:8000/?demo=1 for sample data.

## Tests

```powershell
pytest
```

## Known gaps

- BFit and Hitch have no venue codes yet, so they show no events.
- Events for Drake, IM Field, the Student Activities Center, Pauley and Wooden West show up under "unassigned" until a facility claims them.
- Sign-in codes are printed in the API log until you set up email. See the note in `docker-compose.yml`.