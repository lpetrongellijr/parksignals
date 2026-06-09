# ParkSignals

Automated Disney & Universal ride downtime monitoring system.

## Features
- Pulls live ride data from Queue-Times
- Detects ride downtime/reopenings
- Persists ride state by park
- Runs automatically every 15 minutes via GitHub Actions

## Park configuration
ParkSignals is configured in `parks_config.json`. Magic Kingdom remains enabled
by default. EPCOT, Hollywood Studios, and Animal Kingdom are present as disabled
placeholders so they can be enabled after their monitored ride lists are filled
in.

To run a specific comma-separated set of enabled parks locally or in Actions,
set `PARKSIGNALS_PARKS`, for example:

```bash
PARKSIGNALS_PARKS=magic_kingdom python parksignals.py
```
