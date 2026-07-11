# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from ThemeParks Wiki
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Excludes configured planned closures/refurbishments from reliability analytics
- Supports configured ride-specific operating hours, such as rides that close before the park
- Runs from GitHub Actions workflows triggered by cron-job.org
- Produces workflow artifacts and public website data

## Park configuration
ParkSignals is configured in `parks_config.json`. Magic Kingdom, EPCOT,
Hollywood Studios, and Animal Kingdom are enabled by default, with each park's
monitored attractions listed under `major_rides`.

Each park may also define `planned_closures`. These are refurbishments or other
known maintenance windows that should be visible in logs but excluded from daily
summaries, monthly reliability, trend insights, and projections. Example:

```json
"planned_closures": [
  {
    "ride_name": "Kali River Rapids",
    "starts_on": "2026-06-13",
    "ends_on": "2026-06-30",
    "reason": "refurbishment",
    "source": "Disney refurbishment calendar"
  }
]
```

`ride_name` should match the ThemeParks Wiki ride name already listed in
`major_rides`. `ride_ids` can also be used if a name changes.

Each park may also define `ride_operating_hours` for attractions that regularly
close before or open after the park's regular operating day. These scheduled
ride closures are shown as closed, but they are not counted as downtime. Example:

```json
"ride_operating_hours": [
  {
    "ride_name": "Wildlife Express Train",
    "opens_at": "09:30",
    "closes_at": "16:30",
    "timezone": "America/New_York",
    "reason": "scheduled ride operating hours",
    "source": "configured_ride_operating_hours"
  }
]
```

ParkSignals uses official Disney daily park hours when `park_hours_cache.json`
has current data for the park. The `ParkSignals Park Hours` workflow refreshes
that cache from cron-job.org, currently starting at 7:00 AM Eastern and then
every 6 hours. When no `--date` is passed, the park-hours fetch selects the date
using America/New_York so the workflow follows Walt Disney World's local park
schedule. Cached operating-hour values are also stored in America/New_York.

Official hours are required for downtime monitoring. If official hours are
missing or stale for a park, the monitor marks that park closed for monitoring,
emits a GitHub Actions warning named `Park hours missing`, and suppresses
downtime state changes. There are no generic fallback operating hours.

There are no opening or closing grace periods. If official hours say the park is
open, monitoring runs. If official hours say the park is closed, monitoring is
suppressed.

Special-ticket events do not extend the monitoring window. The official-hours
parser uses the regular `Park Hours` entry only, so events like Mickey's
Not-So-Scary Halloween Party, Mickey's Very Merry Christmas Party, Jollywood
Nights, or Disney After Hours are ignored for downtime tracking unless a future
config explicitly enables event monitoring.

When a run is outside the resolved monitoring window, the monitor still logs the
park and ride ID map, but it suppresses closure transitions and does not update
downtime state.

To run a specific comma-separated set of enabled parks locally or in Actions,
set `PARKSIGNALS_PARKS`, for example:

```bash
PARKSIGNALS_PARKS=magic_kingdom python scripts/run_monitor.py
```

## State storage
`state.json` stores each monitored ride by park. New state records include the
current open status, last seen and change timestamps, downtime start time,
last reopen time, current downtime duration, total completed downtime seconds,
and recent downtime events.

Ride state is not the same as park operating status. If a park is closed or a
run is outside regular operating hours, ParkSignals leaves ride state at the last
tracked in-hours value so normal nightly closures do not become fake downtime.
Current park open/closed-for-monitoring status is reported separately in
`park-status.txt`, `park-status.json`, and `last-run-summary.json`.

Each ride record also stores the ThemeParks Wiki `id` and current `name`, so the
numeric keys in `state.json` can be read without looking them up elsewhere.

If a test run happens after normal monitoring hours and marks many rides as
unavailable, clear that test pollution from `state.json`. Do not delete the test
suite; the tests should remain so future changes keep this behavior covered.

## Monitoring logs and artifacts
Every run prints a monitor summary to the GitHub Actions log. The summary shows
which parks were checked, how many configured rides matched ThemeParks Wiki, current
open/unavailable/planned counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

Planned closures are listed separately as `Planned closures/refurbishments`, so
you can confirm a ride was intentionally ignored instead of silently missing.

The log also prints a `Park hours source` section showing whether each park used
current official hours or whether official hours were unavailable and monitoring
was suppressed.

If a run is outside resolved monitoring hours, the log also prints a
`Downtime tracking suppressed` section. That means the workflow ran and observed
live ride data, but intentionally skipped downtime state changes.

The monitor workflow also uploads output artifacts from `outputs/`:

- `monitor-summary.txt`
- `last-run-summary.json`
- `park-status.txt`
- `park-status.json`
- `analytics-readiness.txt`
- `analytics-summary.json`
- `ride-id-map.json`
- `daily-summary.txt`

It also writes public website data to `public/data/`:

- `latest.json`
- `history.json`
- `intraday.json`

Since-start API archive data is written to `public/data/archive/`:

- `wait-samples.jsonl`: raw wait samples from each accepted monitor run.
- `ride-events.jsonl`: ride down/reopened transition events.
- `park-hours.jsonl`: observed regular operating hours by park/date.
- `daily-ride-metrics.json`: daily ride metrics built from `analytics_history.json`.

`park-status.txt` is the quickest way to confirm whether a park is open for
monitoring or closed/outside regular hours. `analytics-readiness.txt` explains
whether there is enough history for trends and monthly reliability.

To confirm the monitor is working, open the latest ParkSignals Monitor workflow
run in GitHub Actions and review the "Run ParkSignals" step or download the
`parksignals-monitor-outputs` artifact.

The same log also prints an analytics readiness section:

- daily downtime summary inputs
- monthly reliability ranking inputs once 30 days of history are available
- trend inputs once 7 days of history are available
- active downtime projection inputs

Posting and X integration have been removed. ParkSignals now captures operational
data for analytics and the public website only.

## Dry runs
Use dry-run mode to test closures and reopenings against sample data without
calling live APIs or saving `state.json`:

```bash
python scripts/dry_run.py --data samples/dry_run_themeparks_wiki.json --output-dir outputs
```

## Public REST API
ParkSignals includes a read-only JSON REST API in `api/`. The API exposes the
cached data already written to `public/data/`; it does not scrape websites or
call ThemeParks Wiki during request handling.

Install dependencies and start the API locally:

```bash
python -m pip install -r requirements.txt
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

Then open:

- Swagger UI: `http://localhost:8000/api/docs`
- OpenAPI JSON: `http://localhost:8000/api/openapi.json`
- Static OpenAPI spec: `docs/openapi.yaml`

Environment variables:

- `PARKSIGNALS_DATA_DIR`: directory containing `latest.json`, `history.json`, and `intraday.json`; defaults to `public/data`.
- `PARKSIGNALS_PUBLIC_API_BASE_URL`: public API URL used in generated OpenAPI docs; defaults to `https://parksignals-api.onrender.com`.
- `PARKSIGNALS_API_CACHE_TTL_SECONDS`: in-process JSON cache duration; defaults to `30`.
- `PARKSIGNALS_CORS_ORIGINS`: comma-separated allowed CORS origins; defaults to `*`.
- `PARKSIGNALS_API_KEY_REQUIRED`: set to `true` later to require an API key.
- `PARKSIGNALS_API_KEY`: expected API key value when API key auth is enabled.

Authentication is anonymous read-only by default. The API already has an
`X-API-Key` hook so key-based access can be enabled later without changing every
endpoint.

### API endpoints

`GET /api/health`

Returns API health:

```bash
curl http://localhost:8000/api/health
```

`GET /api/parks`

Returns every Disney World park with id, name, status, operating hours, crowd
score, and last updated timestamp:

```bash
curl http://localhost:8000/api/parks
```

`GET /api/parks/{parkId}`

Returns detailed park data. `parkId` can be a public slug such as
`magic-kingdom` or the internal id such as `magic_kingdom`.

```bash
curl http://localhost:8000/api/parks/magic-kingdom
```

`GET /api/rides`

Returns all rides with ride id, name, park, wait, status, Lightning Lane field,
virtual queue field, and last updated timestamp. Lightning Lane and virtual
queue fields are currently `null` unless future data capture adds them.

```bash
curl http://localhost:8000/api/rides
```

Filter by park:

```bash
curl "http://localhost:8000/api/rides?park=magic-kingdom"
```

`GET /api/rides/{rideId}`

Returns complete ride details, including current fields, downtime fields,
history, and intraday samples. `rideId` can be the ThemeParks Wiki id or a
slugified ride name.

```bash
curl http://localhost:8000/api/rides/space-mountain
```

`GET /api/waits`

Returns wait-time-only records:

```bash
curl http://localhost:8000/api/waits
```

Filter waits by park:

```bash
curl "http://localhost:8000/api/waits?park=epcot"
```

`GET /api/forecast`

Returns derived ParkSignals forecast data. Forecasts are currently based on
current average waits and official park hours, with method metadata included in
each response.

```bash
curl http://localhost:8000/api/forecast
```

`GET /api/status`

Returns overall operational status for all parks:

```bash
curl http://localhost:8000/api/status
```

`GET /api/history/ride-events`

Returns archived ride down/reopened events since the archive started. Supports
optional `park`, `ride`, `startDate`, and `endDate` filters:

```bash
curl "http://localhost:8000/api/history/ride-events?park=magic-kingdom&ride=space-mountain"
```

`GET /api/history/wait-samples`

Returns archived raw wait samples. Supports optional `park`, `ride`,
`startDate`, and `endDate` filters:

```bash
curl "http://localhost:8000/api/history/wait-samples?park=epcot&startDate=2026-07-10"
```

`GET /api/history/park-hours`

Returns archived regular park operating hours. Supports optional `park`,
`startDate`, and `endDate` filters:

```bash
curl "http://localhost:8000/api/history/park-hours?park=animal-kingdom"
```

`GET /api/history/daily-ride-metrics`

Returns since-start daily ride metrics, currently generated from
`analytics_history.json`:

```bash
curl http://localhost:8000/api/history/daily-ride-metrics
```

### Custom GPT Action notes

Use `https://parksignals-api.onrender.com/api/openapi.json` as the schema URL
for a Custom GPT Action. The generated schema includes the deployed Render URL:

```yaml
servers:
  - url: https://parksignals-api.onrender.com
```

The GPT can answer current park and ride questions from:

- `/api/status` for a compact all-parks read
- `/api/parks/{parkId}` for park-specific answers
- `/api/rides?park=magic-kingdom` for ride lists
- `/api/rides/{rideId}` for ride-specific history and intraday context
- `/api/forecast` for derived crowd/timing guidance
- `/api/history/daily-ride-metrics` for since-start daily reliability and wait summaries
- `/api/history/wait-samples` for raw wait samples
- `/api/history/ride-events` for ride open/close event history
- `/api/history/park-hours` for historical park operating hours

Because the API is anonymous read-only at first, no authentication schema is
required for the initial Custom GPT Action. If API key auth is enabled later,
send the key in an `X-API-Key` header.

## Tests
Run the test suite locally with:

```bash
python -m unittest discover -s tests
```

Pull requests run the same tests in GitHub Actions and also execute a dry run
that uploads sample output artifacts.

## Daily summaries
The separate `ParkSignals Daily Summary` workflow runs once per day from
cron-job.org and can also be started manually. It generates daily summary
artifacts from the current persisted state.

Trend insight previews require at least 7 days of collected state history.
Monthly reliability previews require at least 30 days of collected state history
and use the previous completed calendar month in the park timezone. For example,
a run on July 1 Eastern can produce a title like `Disney World Reliability - June 2026`
once 30 days of ParkSignals history are available.

## Next verification checklist
Check the next generated artifacts tomorrow and confirm:

- `park-status.txt` shows `official hours unavailable` if the official cache is missing or stale.
- The GitHub Actions run shows a `Park hours missing` warning if official hours are unavailable.
- `analytics-readiness.txt` holds trend insights until 7 days of history are available.
- `analytics-readiness.txt` holds monthly reliability until 30 days of history are available.
- `analytics-summary.json` includes `data_age_days`, `trend_insights_ready`, and `monthly_reliability_ready`.
