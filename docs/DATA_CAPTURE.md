# ParkSignals Data Capture

ParkSignals keeps long-term analytics in `analytics_history.json`.

This file is meant to answer questions that are useful later, even if we do not know the exact reports yet:

- how many times each ride went down per day, week, and month
- how long each ride was down per day, week, and month
- average posted wait time per ride per day
- min and max posted wait time per ride per day
- which monitor runs were accepted for tracking

## Why JSON first

JSON is the source of truth because the data is naturally nested:

`date -> park -> ride -> metrics`

That is easier and safer than forcing the first version into a flat spreadsheet. CSV or Excel exports can be generated from this later once we know which views are most useful.

The monitor also writes artifact summaries:

- `data-capture-summary.txt` for a quick human check
- `data-capture-summary.json` for daily, weekly, and monthly rollups

## Stored Daily Metrics

Each ride/day record stores:

- `samples`: accepted monitor samples captured for that ride
- `open_samples`: samples where the ride was operating
- `down_samples`: samples where the ride was unavailable
- `planned_closure_samples`: samples where the ride was in planned closure/refurbishment
- `unknown_samples`: samples where the source status was unknown
- `wait_time_samples`: number of samples with a posted wait time
- `wait_time_total`: total wait minutes across samples
- `average_wait_time`: average posted wait for the day
- `min_wait_time`: lowest posted wait for the day
- `max_wait_time`: highest posted wait for the day
- `down_event_count`: number of new down transitions captured that day
- `downtime_seconds`: total operational downtime captured for that day

Suppressed parks are not counted. That means before-hours, after-hours, opening grace, closing grace, and missing-hours suppression do not pollute the analytics.

## Rollups

`outputs/data-capture-summary.json` includes generated rollups for:

- daily detail
- weekly totals
- monthly totals

These rollups are generated from `analytics_history.json`; they are artifacts for review, not the source of truth.

## Future Export Options

Good next exports once the data has a few days of history:

- `analytics_history.csv`: one row per ride per day
- `weekly_ride_reliability.csv`: one row per ride per week
- `monthly_ride_reliability.csv`: one row per ride per month
- `.xlsx` workbook with tabs for Daily, Weekly, Monthly, and Ride Detail
