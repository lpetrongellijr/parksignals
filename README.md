# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Runs from GitHub Actions workflows triggered by cron-job.org
- Produces workflow artifacts for monitor summaries, post previews, post safety plans, park status, ride ID maps, analytics inputs, and disabled X connection readiness

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

Official hours are required for downtime monitoring. If official hours are
missing or stale for a park, the monitor marks that park closed for monitoring
and suppresses downtime state changes. The configured `monitoring_hours` values
remain in `parks_config.json` for reference, but they are not used as generic
fallback hours for live downtime tracking.

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
open/unavailable counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

The log also prints a `Park hours source` section showing whether each park used
current official hours or whether official hours were unavailable and monitoring
was suppressed. Generic configured fallback hours are logged as ignored when
official hours are unavailable.

If a run is outside resolved monitoring hours, the log also prints a
`Downtime tracking suppressed` section. That means the workflow ran and observed
Queue-Times data, but intentionally skipped downtime state changes.

The monitor workflow also uploads output artifacts from `outputs/`:

- `monitor-summary.txt`
- `last-run-summary.json`
- `park-status.txt`
- `park-status.json`
- `content-pillar-readiness.txt`
- `post-candidates.json`
- `post-previews.txt`
- `post-dispatch-plan.txt`
- `post-dispatch-plan.json`
- `x-connection-status.txt`
- `x-connection-status.json`
- `analytics-summary.json`
- `ride-id-map.json`
- `daily-summary.txt`

`park-status.txt` is the quickest way to confirm whether a park is open for
monitoring or closed/outside regular hours. `post-previews.txt` is the easiest
review file for draft post text. It shows draft text for the currently available
post candidates across single-ride alerts, multi-ride alerts, daily summaries,
monthly reliability, trend insights, and projection insights. `post-candidates.json`
carries the same candidates in structured form for future automated posting.
Posting remains disconnected.

`post-dispatch-plan.txt` applies the posting safety policy and explains whether
each candidate would post in dry-run mode or be skipped. It includes skip reasons
such as missing X credentials, park closed for monitoring, duplicate posted key,
empty summary, disabled pillar, or text over the configured character limit.

`x-connection-status.txt` reports whether the X credentials are present in
GitHub Actions secrets. It never prints secret values. Posting is still blocked
unless `PARKSIGNALS_X_POSTING_ENABLED` is explicitly set to `true`, and the
workflows currently set it to `false`.

To confirm the monitor is working, open the latest ParkSignals Monitor workflow
run in GitHub Actions and review the "Run ParkSignals" step or download the
`parksignals-monitor-outputs` artifact.

The same log also prints a content pillar readiness section:

- real-time single ride closure/reopen events
- active multi-ride closure candidates
- multi-ride reopening candidates from the current run
- daily downtime summary inputs
- monthly reliability ranking inputs once 30 days of history are available
- trend inputs once 7 days of history are available
- active downtime projection inputs

These are generated as operational logs and artifacts only. They prepare the
data needed for future automated posting and insight workflows without
connecting X posting yet.

## Posting safety
Posting is controlled by `posting_policy.json` and recorded in `posting_log.json`.
The current policy keeps real posting disabled and dry-run planning enabled.

Safety features now in place:

- Global posting switch is off by default.
- Workflows hard-set `PARKSIGNALS_X_POSTING_ENABLED=false`.
- Per-pillar and per-post-type toggles exist in `posting_policy.json`.
- Candidates are blocked if required X credentials are missing.
- Real-time posts are blocked outside park monitoring hours.
- Empty daily summaries and empty analytics posts are blocked.
- Over-length posts are blocked using `max_post_characters`.
- Duplicate protection checks `posted_keys` and prior confirmed posted decisions.
- Dry-run decisions are logged, while real posted keys remain separate for future live posting.

## X connection readiness
Add X credentials as GitHub Actions repository secrets only. Do not commit them
and do not paste them into issues, logs, or chat.

Required secrets for future posting readiness:

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

Optional secret:

- `X_BEARER_TOKEN`

After the next Monitor or Daily Summary run, download the artifact and open
`x-connection-status.txt`. If all required credentials are present, it will show
`Ready for manual connection test: true`. That still does not post anything.

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

Trend insight previews require at least 7 days of collected state history.
Monthly reliability previews require at least 30 days of collected state history
and use the previous completed calendar month in the park timezone. For example,
a run on July 1 Eastern can produce a title like `Disney World Reliability - June 2026`
once 30 days of ParkSignals history are available.

## Next verification checklist
Check the next generated artifacts tomorrow and confirm:

- `park-status.txt` shows `official hours unavailable` instead of generic fallback hours if the official cache is missing or stale.
- `content-pillar-readiness.txt` holds trend previews until 7 days of history are available.
- `content-pillar-readiness.txt` holds monthly reliability previews until 30 days of history are available.
- `analytics-summary.json` includes `data_age_days`, `trend_insights_ready`, and `monthly_reliability_ready`.
- The post still begins with `PARKSIGNALS // Disney World` and keeps `#DisneyWorld` as the priority hashtag.
