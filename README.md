# Maine Court Alerts Monitor

Monitors the [Maine Judicial Branch court alerts page](https://www.courts.maine.gov/courts/alerts.shtml)
every 10 minutes and sends a Pushover notification when alerts are added,
removed, or changed. Designed to run free, forever, on GitHub Actions.

Especially useful during winter — get a push notification the moment a
snow-day closing is posted, including overnight/early-morning postings.

## What it does

- Fetches the alerts page every 10 minutes, 24/7.
- Parses the "Active Alerts & Closings" table into `{location: notice}` pairs.
- Diffs against the last seen state (stored in `state/alerts.json`).
- On change, sends a Pushover notification per affected court:
  - **🚨 New alert** — priority 1 (bypasses Pushover quiet hours).
  - **🔄 Updated alert** — priority 1, shows before/after.
  - **✅ Cleared** — priority 0 (normal).
- Commits the new state back to the repo so alerts never re-fire for the same notice.

## Setup

### 1. Get Pushover credentials

1. Buy the Pushover app ($5 one-time, iOS or Android) and create an account
   at [pushover.net](https://pushover.net/).
2. Your **User Key** is shown on the main dashboard after login.
3. Create an application: go to *Apps & Plugins* → *Create an Application*.
   Name it "Maine Court Alerts" or similar. Copy the generated **API Token**.

### 2. Create the GitHub repo

1. Create a new **public** repo on GitHub (public = unlimited free Actions minutes).
2. Push these files to it:
   ```
   monitor.py
   requirements.txt
   .gitignore
   .github/workflows/monitor.yml
   README.md
   ```
3. In the repo settings, go to **Settings → Secrets and variables → Actions**
   and add two repository secrets:
   - `PUSHOVER_TOKEN` — your application API token.
   - `PUSHOVER_USER` — your user key.
4. Go to the **Actions** tab and enable workflows if prompted.

### 3. Verify it works

From the **Actions** tab, open the "Maine Court Alerts Monitor" workflow and
click **Run workflow** to trigger it manually. The first run establishes a
baseline and sends one low-priority "monitor started" notification so you know
the pipeline is wired up. After that, you'll only hear from it when something
actually changes.

## Local testing

```bash
pip install -r requirements.txt

# Send a test Pushover notification (requires env vars set).
export PUSHOVER_TOKEN=your_token
export PUSHOVER_USER=your_user_key
python monitor.py --test

# See what changes would be detected without sending notifications or saving state.
python monitor.py --dry-run
```

## Cost

- **GitHub Actions:** $0. Scheduled workflows on public repos are unlimited.
- **Pushover:** $5 one-time for the mobile app. No recurring fees.
- **Total ongoing:** $0/month.

## Notes and caveats

- **GitHub cron timing:** scheduled workflows can be delayed a few minutes
  under heavy load. In practice most runs start within 1–2 minutes of the
  scheduled time. For a 10-minute cadence this is negligible.
- **Night postings:** because this runs 24/7, closings posted at 3am will
  reach you within ~10 minutes of being published.
- **If the page structure changes:** the script will fail loudly rather than
  silently miss alerts, and GitHub will email you about the failed workflow.
- **First run:** sends one "monitor initialized" notification instead of
  spamming you with every currently-listed alert.

## Customization ideas

- **Filter to specific courts:** in `monitor.py`, filter the `current` dict
  after `fetch_alerts()` — e.g., only keep rows whose location contains
  "Cumberland" or "Portland".
- **Change polling frequency:** edit the `cron` line in
  `.github/workflows/monitor.yml`. `*/5 * * * *` for every 5 minutes, etc.
- **Different notification channel:** swap `send_pushover()` for a Telegram
  bot, Discord webhook, or ntfy.sh call — the rest of the script is channel-agnostic.

## Troubleshooting

- **No notifications arriving:** run `python monitor.py --test` locally to
  confirm Pushover credentials work. Check the Actions tab for failed runs.
- **Workflow stopped running:** GitHub disables scheduled workflows on repos
  with no activity for 60 days. The state-file commits this project makes
  should keep the repo active indefinitely, but if the page never changes for
  months, you may need to push a trivial commit.
- **Duplicate notifications on every run:** means the state file isn't being
  committed. Check that the workflow has `permissions: contents: write` and
  that the "Commit state changes" step is succeeding.
