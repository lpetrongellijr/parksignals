# ParkSignals

Automated ride downtime monitor for theme park alerts.

## What it does

- Pulls live ride data from Queue-Times
- Filters for major attractions
- Detects open/closed status changes
- Generates X-ready alert copy
- Optionally posts to X if API secrets are added
- Stores ride status in `state/ride_status.json`

## GitHub setup

1. Create a new GitHub repo named `parksignals`.
2. Upload these files/folders.
3. Go to **Settings → Actions → General**.
4. Under **Workflow permissions**, choose **Read and write permissions**.
5. Commit and push.
6. Go to **Actions → ParkSignals Monitor → Run workflow** to test manually.

## X posting setup, later

Add these GitHub repository secrets:

- `X_CONSUMER_KEY`
- `X_CONSUMER_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

If those are not set, the workflow will only print alert drafts.

## Customize rides

Edit `config.json` to change tracked parks and major rides.
