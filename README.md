# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Runs automatically every 15 minutes via GitHub Actions
- Produces workflow artifacts for monitor summaries, post candidates, ride ID maps, and analytics inputs

## Park configuration
ParkSignals is configured in `parks_config.json`. Magic Kingdom, EPCOT,
Hollywood Studios, and Animal Kingdom are enabled by default, with each park's
monitored attractions listed under `major_rides`.

Each park also defines post metadata such as `resort_name`, `resort_hashtag`,
and `park_hashtag` so alert text can follow the master template system in
`docs/MASTER_POST_TEMPLATES.md`.

To run a specific comma-separated set of enabled parks locally or in Actions,
set `PARKSIGNALS_PARKS`, for example:

```bash
PARKSIGNALS_PARKS=magic_kingdom python parksignals.py
```

## State storage
`state.json` stores each monitored ride by park. New state records include the
current open status, last seen and change timestamps, downtime start time,
last reopen time, current downtime duration, total completed downtime seconds,
and recent downtime events.

Each ride record also stores the Queue-Times `id` and current `name`, so the
numeric keys in `state.json` can be read without looking them up elsewhere.

## Monitoring logs and artifacts
Every run prints a monitor summary to the GitHub Actions log. The summary shows
which parks were checked, how many configured rides matched Queue-Times, current
open/unavailable counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

The monitor workflow also uploads output artifacts from `outputs/`:

- `monitor-summary.txt`
- `content-pillar-readiness.txt`
- `post-candidates.json`
- `analytics-summary.json`
- `ride-id-map.json`
- `daily-summary.txt`

To confirm the scheduled monitor is working, open the latest ParkSignals
Monitor workflow run in GitHub Actions and review the "Run ParkSignals" step
or download the `parksignals-monitor-outputs` artifact.

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
The separate `ParkSignals Daily Summary` workflow runs once per day and can also
be started manually. It generates daily summary artifacts from the current
persisted state without saving state or posting externally.
