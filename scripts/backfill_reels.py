"""Plan a Reel for every post that is already live on Instagram but has none, one per day, in a gap of the daily schedule.

Usage: python scripts/backfill_reels.py            (plans them; safe to run again, it never changes a Reel that already has a plan)

For each such post it writes a pending entry to state/reels.json with an explicit `post_at` time. The Reel workflow then renders the
videos, and the publisher posts each one at its time (publish.py, find_due_reel). Cancel or move any of them from the dashboard.
Config (config.json): backfill_reel_time (New York time, default "18:15"), backfill_per_day (default 1).
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def main():
    config = load(ROOT / "config.json", {})
    tz = ZoneInfo(config["timezone"])
    reels, posted, stats = load(ROOT / "state" / "reels.json", {}), load(ROOT / "state" / "posted.json", {}), load(ROOT / "state" / "stats.json", [])
    posts = {}
    for path in (ROOT / "queue").glob("*/*/post.json"):
        post = load(path, {})
        if post.get("id"):
            posts[post["id"]] = post

    live = {}                                              # post id -> when it went live (for ordering)
    for pid, rec in posted.items():
        if rec.get("status") == "posted" and rec.get("posted_at"):
            live[pid] = rec["posted_at"]
    for e in stats:
        if e.get("id") and e.get("kind") != "reel":
            live.setdefault(e["id"], e.get("posted_local") or "")
    todo = [pid for pid in sorted(live, key=lambda p: live[p])
            if pid in posts and not posts[pid].get("spare") and posts[pid].get("reel_slot") is None and pid not in reels]
    if not todo:
        print("Every live post already has a Reel or a plan.")
        return

    hh, mm = map(int, config.get("backfill_reel_time", "18:15").split(":"))
    per_day = max(1, int(config.get("backfill_per_day", 1)))
    day = datetime.now(tz).date() + timedelta(days=1)       # starts tomorrow (New York date)
    print("Planned Reels for posts that have none:")
    for i, pid in enumerate(todo):
        d = day + timedelta(days=i // per_day)
        offset = random.Random("backfill-%s-%d" % (d.isoformat(), i % per_day)).randint(-25, 25) + (i % per_day) * 150
        at = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz) + timedelta(minutes=offset)
        reels[pid] = {"status": "pending", "backfill": True, "post_at": at.astimezone(timezone.utc).isoformat(), "attempts": 0}
        print("  %-16s %-46s -> %s (New York)" % (pid, posts[pid]["title"][:46], at.strftime("%a %b %d %H:%M")))
    (ROOT / "state" / "reels.json").write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
