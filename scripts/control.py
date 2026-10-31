"""Carry out one control-panel action. Run by the Control workflow (started from the dashboard).

Usage: python scripts/control.py ACTION [TARGET]

  pause / resume              stop or restart all publishing
  remove POST_ID              never publish this queued post (kept for the record)
  restore POST_ID             undo "remove"
  post_now POST_ID            publish this post at the next check, ignoring its time slot
                              (the 45-minute gap and daily cap still apply)
  posts_per_day N             1-5 posts a day from the next research run on
  delete_instagram POST_ID    delete a live post from Instagram (whole carousel)
  refresh_dashboard           just rebuild the dashboard

Every action is written to state/control_log.json, which the dashboard shows. This script
never exits with an error, so nothing emails anyone; problems show up in the log.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
POSTED = ROOT / "state" / "posted.json"
STATS = ROOT / "state" / "stats.json"
LOG = ROOT / "state" / "control_log.json"
MAX_ATTEMPTS = 3
SLOTS = {1: [3], 2: [1, 5], 3: [1, 3, 5], 4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5]}


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def find_media_id(post_id, posted):
    if posted.get(post_id, {}).get("media_id"):
        return posted[post_id]["media_id"]
    for s in load(STATS, []):
        if post_id in (s.get("id"), s.get("media_id")):
            return s.get("media_id")
    return None


def delete_from_instagram(media_id, config):
    url = "https://%s/%s/%s?%s" % (config.get("graph_host", "graph.instagram.com"), config["graph_api_version"], media_id,
                                   urllib.parse.urlencode({"access_token": os.environ["IG_ACCESS_TOKEN"]}))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=60) as resp:
            return json.loads(resp.read() or b"{}").get("success", True), ""
    except urllib.error.HTTPError as exc:
        return False, "Instagram said %s: %s" % (exc.code, exc.read().decode()[:200])
    except Exception as exc:
        return False, str(exc)[:200]


def run(action, target):
    config = load(CONFIG, {})
    posted = load(POSTED, {})
    now = datetime.now(timezone.utc).isoformat()

    if action in ("pause", "resume"):
        config["paused"] = action == "pause"
        save(CONFIG, config)
        return "Publishing %s." % ("paused" if action == "pause" else "resumed")

    if action == "posts_per_day":
        n = int(target)
        if n not in SLOTS:
            return "Posts per day must be 1 to 5."
        config.update(posts_per_day=n, active_slots=SLOTS[n], max_posts_per_day=n + 1)
        save(CONFIG, config)
        return "Posts per day set to %d (takes effect from the next research run)." % n

    if action in ("remove", "restore", "post_now", "delete_instagram") and not target:
        return "No post was given."

    record = posted.get(target, {})
    if action == "remove":
        if record.get("status") == "posted":
            return "That post is already live; use Delete from Instagram instead."
        posted[target] = dict(record, status="removed", attempts=MAX_ATTEMPTS, removed_at=now)
        save(POSTED, posted)
        return "Removed %s; it will not be published." % target

    if action == "restore":
        if record.get("status") != "removed":
            return "%s was not removed." % target
        posted.pop(target)
        save(POSTED, posted)
        return "Restored %s; it will publish at its time if that hasn't passed (or use Post now)." % target

    if action == "post_now":
        if record.get("status") == "posted":
            return "%s is already live." % target
        record.pop("status", None)
        posted[target] = dict(record, attempts=0, post_now=True, post_now_requested_at=now)
        save(POSTED, posted)
        return "%s will be published at the next check (within a few minutes, unless a post went out in the last %d minutes)." % (
            target, config.get("min_minutes_between_posts", 45))

    if action == "delete_instagram":
        media_id = find_media_id(target, posted)
        if not media_id:
            return "Couldn't find the Instagram post for %s." % target
        ok, error = delete_from_instagram(media_id, config)
        if not ok:
            return "Delete failed: %s. You can delete it in the Instagram app (... > Delete)." % error
        posted[target] = dict(record, status="deleted", deleted_at=now, attempts=MAX_ATTEMPTS)
        save(POSTED, posted)
        return "Deleted %s from Instagram." % target

    if action == "refresh_dashboard":
        return "Dashboard rebuilt."
    return "Unknown action %r." % action


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    target = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    try:
        result = run(action, target)
    except Exception as exc:
        result = "Error: %s" % str(exc)[:200]
    print(result)
    log = load(LOG, [])
    log.insert(0, {"at": datetime.now(timezone.utc).isoformat(), "action": action, "target": target, "result": result})
    save(LOG, log[:50])


if __name__ == "__main__":
    main()
