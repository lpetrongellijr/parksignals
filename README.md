# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Tracks downtime timestamps and completed downtime events for future summaries
- Runs automatically every 15 minutes via GitHub Actions

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

## Monitoring logs
Every run prints a monitor summary to the GitHub Actions log. The summary shows
which parks were checked, how many configured rides matched Queue-Times, current
open/unavailable counts, any status changes, and a ride ID map such as:

```text
159: Frozen Ever After (open, wait 45 min)
```

To confirm the scheduled monitor is working, open the latest ParkSignals
Monitor workflow run in GitHub Actions and review the "Run ParkSignals" step.
