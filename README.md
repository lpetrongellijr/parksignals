# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Excludes configured planned closures/refurbishments from alerts and reliability analytics
- Runs from GitHub Actions workflows triggered by cron-job.org
- Produces workflow artifacts for monitor summaries, post previews, post safety plans, park status, ride ID maps, analytics inputs, and disabled X connection readiness

## Park configuration
ParkSignals is configured in `parks_config.json`. Magic Kingdom, EPCOT,
Hollywood Studios, and Animal Kingdom are enabled by default, with each park's
monitored attractions listed under `major_rides`.

Each park also defines post metadata such as `resort_name`, `resort_hashtag`,
and `park_hashtag` so alert text can follow the master template system in
`docs/MASTER_POST_TEMPLATES.md`.

Each park may also define `planned_closures`. These are refurbishments or other
known maintenance windows that should be visible in logs but excluded from alert
posts, multi-ride alerts, daily summaries, monthly reliability, trend insights,
and projections. Example:

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

`ride_name` should match the Queue-Times ride name already listed in
`major_rides`. `ride_ids` can also be used if a name changes.

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

Each ride record also stores the Queue-Times `id` and current `name`, so the
numeric keys in `state.json` can be read without looking them up elsewhere.

If a test run happens after normal monitoring hours and marks many rides as
unavailable, clear that test pollution from `state.json`. Do not delete the test
suite; the tests should remain so future changes keep this behavior covered.

## Monitoring logs and artifacts
Every run prints a monitor summary to the GitHub Actions log. The summary shows
which parks were checked, how many configured rides matched Queue-Times, current
open/unavailable/planned counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

Planned closures are listed separately as `Planned closures/refurbishments`, so
you can confirm a ride was intentionally ignored instead of silently missing.

The log also prints a `Park hours source` section showing whether each park used
current official hours or whether official hours were unavailable and monitoring
was suppressed.
