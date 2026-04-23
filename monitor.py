#!/usr/bin/env python3
"""
Maine Courts Alerts Monitor

Checks the Maine Judicial Branch court alerts page for changes and sends
Pushover notifications when alerts are added, removed, or modified.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

ALERTS_URL = "https://www.courts.maine.gov/courts/alerts.shtml"
STATE_FILE = Path("state/alerts.json")
PUSHOVER_API = "https://api.pushover.net/1/messages.json"
USER_AGENT = "MaineCourtAlertsMonitor/1.0 (personal notification tool)"

# Pushover API limits
PUSHOVER_TITLE_LIMIT = 250
PUSHOVER_MESSAGE_LIMIT = 1024


def fetch_alerts() -> Dict[str, str]:
    """Fetch the alerts page and return current alerts as {location: notice}.

    Raises RuntimeError if the alerts table can't be found — this likely means
    the page structure changed and the script needs updating.
    """
    response = requests.get(
        ALERTS_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Find the alerts table by matching header text rather than position.
    # The page has other tables (navigation, layout), so we identify ours
    # by the presence of "Location" and "Notice" header cells.
    alerts_table = None
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "location" in headers and "notice" in headers:
            alerts_table = table
            break

    if alerts_table is None:
        raise RuntimeError(
            "Could not find the alerts table on the page. "
            "The page structure may have changed — check "
            f"{ALERTS_URL} and update the scraper."
        )

    alerts: Dict[str, str] = {}
    for row in alerts_table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue  # header row or malformed
        location = cells[0].get_text(" ", strip=True)
        notice = cells[1].get_text(" ", strip=True)
        if location:
            alerts[location] = notice

    return alerts


def load_previous_state() -> Tuple[Dict[str, str], bool]:
    """Return (state, is_first_run)."""
    if not STATE_FILE.exists():
        return {}, True
    try:
        with STATE_FILE.open() as f:
            return json.load(f), False
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read state file ({e}); treating as first run.",
              file=sys.stderr)
        return {}, True


def save_state(alerts: Dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(alerts, f, indent=2, sort_keys=True)
        f.write("\n")


def send_pushover(title: str, message: str, priority: int = 0,
                  dry_run: bool = False) -> None:
    """Send a single Pushover notification."""
    if dry_run:
        print(f"[DRY RUN] priority={priority}")
        print(f"  Title:   {title}")
        print(f"  Message: {message}")
        print()
        return

    token = os.environ.get("PUSHOVER_TOKEN")
    user = os.environ.get("PUSHOVER_USER")
    if not token or not user:
        print("ERROR: PUSHOVER_TOKEN and PUSHOVER_USER env vars must be set.",
              file=sys.stderr)
        sys.exit(1)

    response = requests.post(
        PUSHOVER_API,
        data={
            "token": token,
            "user": user,
            "title": title[:PUSHOVER_TITLE_LIMIT],
            "message": message[:PUSHOVER_MESSAGE_LIMIT],
            "priority": priority,
            "url": ALERTS_URL,
            "url_title": "View full alerts page",
        },
        timeout=30,
    )
    response.raise_for_status()


def diff_alerts(
    old: Dict[str, str],
    new: Dict[str, str],
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str, str]]]:
    """Return (added, removed, changed).

    added:   [(location, notice), ...]
    removed: [(location, old_notice), ...]
    changed: [(location, old_notice, new_notice), ...]
    """
    old_keys = set(old)
    new_keys = set(new)

    added = [(loc, new[loc]) for loc in sorted(new_keys - old_keys)]
    removed = [(loc, old[loc]) for loc in sorted(old_keys - new_keys)]
    changed = [
        (loc, old[loc], new[loc])
        for loc in sorted(old_keys & new_keys)
        if old[loc] != new[loc]
    ]
    return added, removed, changed


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test", action="store_true",
        help="Send a test Pushover notification and exit."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect and print changes without sending notifications or saving state."
    )
    args = parser.parse_args()

    if args.test:
        send_pushover(
            title="Maine Courts Monitor — test",
            message="If you're reading this, Pushover is configured correctly.",
        )
        print("Test notification sent.")
        return 0

    try:
        current = fetch_alerts()
    except Exception as e:
        print(f"Failed to fetch/parse alerts: {e}", file=sys.stderr)
        # Fail the job so GitHub Actions emails about it. Don't touch state.
        return 1

    previous, first_run = load_previous_state()
    added, removed, changed = diff_alerts(previous, current)

    if first_run:
        print(f"First run — baseline established with {len(current)} active alert(s).")
        if not args.dry_run:
            if current:
                # List each court currently on the alerts page so the user sees
                # exactly what's being treated as the baseline.
                court_list = "\n".join(f"• {loc}" for loc in sorted(current))
                message = (
                    f"Monitoring initialized. {len(current)} active alert(s) "
                    f"currently on the page:\n\n{court_list}\n\n"
                    "You'll be notified of future changes."
                )
            else:
                message = (
                    "Monitoring initialized. No active alerts on the page right now. "
                    "You'll be notified when any appear."
                )
            send_pushover(
                title="Maine Courts monitor started",
                message=message,
                priority=-1,
            )
            save_state(current)
        return 0

    if not (added or removed or changed):
        print("No changes.")
        return 0

    print(f"Changes detected: {len(added)} added, {len(changed)} changed, "
          f"{len(removed)} removed.")

    # New closings/alerts — priority 1 bypasses Pushover quiet hours, which is
    # what we want for overnight weather postings.
    for loc, notice in added:
        send_pushover(
            title=truncate(f"🚨 New court alert: {loc}", PUSHOVER_TITLE_LIMIT),
            message=notice,
            priority=1,
            dry_run=args.dry_run,
        )

    for loc, old_notice, new_notice in changed:
        body = f"Previous:\n{truncate(old_notice, 400)}\n\nNow:\n{truncate(new_notice, 400)}"
        send_pushover(
            title=truncate(f"🔄 Updated court alert: {loc}", PUSHOVER_TITLE_LIMIT),
            message=body,
            priority=1,
            dry_run=args.dry_run,
        )

    for loc, _old_notice in removed:
        send_pushover(
            title=truncate(f"✅ Cleared: {loc}", PUSHOVER_TITLE_LIMIT),
            message=f"The alert previously listed for {loc} has been removed.",
            priority=0,
            dry_run=args.dry_run,
        )

    if not args.dry_run:
        save_state(current)

    return 0


if __name__ == "__main__":
    sys.exit(main())
