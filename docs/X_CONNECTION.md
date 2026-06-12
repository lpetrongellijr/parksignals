# X Connection Runbook

ParkSignals can now test X credentials and has a guarded posting transport, but live posting remains off by default.

## Current safety state

Live posting requires both switches to be enabled:

1. `posting_policy.json` must set `posting_enabled` to `true`.
2. The workflow environment must set `PARKSIGNALS_X_POSTING_ENABLED` to `true`.

The Monitor and Daily Summary workflows currently set `PARKSIGNALS_X_POSTING_ENABLED` to `false`, so they cannot post.

## Manual connection test

Run the `ParkSignals X Connection Test` workflow from GitHub Actions.

Expected artifact: `parksignals-x-connection-test`

Open `x-connection-test.txt` and confirm:

- `Ready for manual connection test: true`
- `Connection test passed: true`
- `Authenticated user` shows the expected X account
- `Posting enabled: false`

This workflow authenticates with X but does not create a post.

## Monitor and Daily Summary artifacts

Monitor and Daily Summary also create dispatch artifacts:

- `x-dispatch-results.txt`
- `x-dispatch-results.json`

While posting is disabled, these should say no posts were ready to dispatch.

When posting is enabled, dispatch sends one post at a time, waits 60 seconds, then sends the next ready post. Priority is:

1. Single ride closures
2. Single ride reopenings
3. Multi-ride closures
4. Multi-ride reopenings
5. Daily summaries
6. Monthly reliability
7. Trend insights
8. Projection insights

## Before enabling live posts

Confirm all of these first:

- Park hours are current.
- `park-status.txt` shows only regular park hours are used for monitoring.
- `post-dispatch-plan.txt` has no blocked candidates you expected to post.
- Preview text is under 280 characters.
- Duplicate protection is working through `posting_log.json`.
- The X connection test passes for the intended account.

Only then change both live-posting switches intentionally.
