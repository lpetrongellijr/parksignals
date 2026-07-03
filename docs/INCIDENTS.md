# ParkSignals Incident Notes

## 2026-07-01 to 2026-07-03: Data refresh interruption

ParkSignals data for this window should be treated as unreliable for trend,
downtime, and reliability analysis.

The issue was caused by a GitHub repository ownership move that broke the
automation trigger path and left the public data feed stale. This was a
pipeline glitch, not a park operations signal.

The feed was confirmed working again when `public/data/latest.json` updated to
`generated_at: 2026-07-03T20:56:55Z`.

Use data from after that timestamp as the restart point for normal monitoring.
