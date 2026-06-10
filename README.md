# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Runs from GitHub Actions workflows triggered by cron-job.org
- Produces workflow artifacts for monitor summaries, post previews, ride ID maps, and analytics inputs

## Park configuration
ParkSignals is configured in `parks_config.json`. Magic Kingdom, EPCOT,
Hollywood Studios, and Animal Kingdom are enabled by default, with each park's
monitored attractions listed under `major_rides`.

Each park also defines post metadata such as `resort_name`, `resort_hashtag`,
and `park_hashtag` so alert text can follow the master template system in
`docs/MASTER_POST_TEMPLATES.md`.

ParkSignals uses official Disney daily park hours when `park_hours_cache.json`
has current data for the park. The `ParkSignals Park Hours` workflow refreshes
that cache from cron-job.org, currently starting at 7:00 AM Eastern and then
every 6 hours. When no `--date` is passed, the park-hours fetch selects the date
using America/New_York so the workflow follows Walt Disney World's local park
schedule. Cached operating-hour values are also stored in America/New_York.

If official hours are missing or stale, the monitor falls back to the configured
`monitoring_hours` in `parks_config.json`.

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

Each ride record also stores the Queue-Times `id` and current `name`, so the
numeric keys in `state.json` can be read without looking them up elsewhere.

If a test run happens after normal monitoring hours and marks many rides as
unavailable, clear that test pollution from `state.json`. Do not delete the test
suite; the tests should remain so future changes keep this behavior covered.

## Monitoring logs and artifacts
Every run prints a monitor summary to the GitHub Actions log. The summary shows
which parks were checked, how many configured rides matched Queue-Times, current
open/unavailable counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

The log also prints a `Park hours source` section showing whether each park used
`official_disney_calendar` or `configured_fallback` hours.

If a run is outside resolved monitoring hours, the log also prints a
`Downtime tracking suppressed` section. That means the workflow ran and observed
Queue-Times data, but intentionally skipped downtime state changes.

The monitor workflow also uploads output artifacts from `outputs/`:

- `monitor-summary.txt`
- `last-run-summary.json`
- `content-pillar-readiness.txt`
- `post-candidates.json`
- `post-previews.txt`
- `analytics-summary.json`
- `ride-id-map.json`
- `daily-summary.txt`

`post-previews.txt` is the easiest review file. It shows draft text for the
currently available post candidates across single-ride alerts, multi-ride alerts,
daily summaries, 30-day analytics, trend insights, and projection insights.
`post-candidates.json` carries the same candidates in structured form for future
automated posting. Posting remains disconnected.

To confirm the monitor is working, open the latest ParkSignals Monitor workflow
run in GitHub Actions and review the "Run ParkSignals" step or download the
`parksignals-monitor-outputs` artifact.

The same log also prints a content pillar readiness section:

- real-time single ride closure/reopen events
- active multi-ride closure candidates
- multi-ride reopening candidates from the current run
- daily downtime summary inputs
- 30-day downtime ranking inputs
- trend and active downtime projection inputs

These are generated as operational logs and artifacts only. They prepare the
data needed for future automated posting and insight workflows without
connecting X posting yet.

## Dry runs
Use dry-run mode to test closures and reopenings against sample data without
calling Queue-Times or saving `state.json`:

```bash
python scripts/dry_run.py --data samples/dry_run_queue_times.json --output-dir outputs
```

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
artifacts from the current persisted state without saving state or posting
externally.
