"""Build docs/index.html, the dashboard page: status, today's posts, followers, post statistics.

Plain script: no AI, no Instagram calls. It only reads files already in the repo
(state/*.json, state/followers.csv, queue/) and writes docs/index.html. Run by the Publish
workflow, which rewrites the page when something changed or at least once an hour.

Usage: python3 scripts/dashboard.py
"""
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publish  # noqa: E402  (for slot_time, the same posting times the publisher uses)

OUT = ROOT / "docs" / "index.html"
PING = ROOT / "state" / "ping.json"
MARK = re.compile(r"/\*DATA\*/(.*?)/\*END\*/", re.S)
REFRESH_MINUTES = 60
MIN_GROUP, MATURE_HOURS = 3, 48


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def record_mac_ping(now):
    """The Mac mini wakes the Publish workflow with a manual run; remember when we last saw that."""
    ping = read_json(PING, {})
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        ping["last_dispatch_utc"] = now.isoformat()
        PING.write_text(json.dumps(ping) + "\n")
    return ping.get("last_dispatch_utc")


def build(now):
    config = publish.load_config()
    tz = ZoneInfo(config["timezone"])
    today = datetime.now(tz).date()
    posted = read_json(ROOT / "state" / "posted.json", {})
    stats = read_json(ROOT / "state" / "stats.json", [])
    by_id = {s["id"]: s for s in stats if s.get("id")}

    # --- today's queue
    today_posts = []
    for path in sorted((ROOT / "queue" / today.isoformat()).glob("*/post.json")):
        post = json.loads(path.read_text())
        rec = posted.get(post["id"], {})
        today_posts.append({
            "id": post["id"], "title": post["title"], "category": post.get("category", ""), "slot": post["slot"],
            "scheduled_utc": publish.slot_time(config, today, post["slot"]).astimezone(timezone.utc).isoformat(),
            "status": rec.get("status"), "error": rec.get("error"), "posted_at": rec.get("posted_at"),
            "permalink": by_id.get(post["id"], {}).get("permalink"),
        })

    # --- posts on Instagram, newest first
    posts = []
    for s in sorted(stats, key=lambda s: s.get("posted_local", ""), reverse=True):
        posts.append({k: s.get(k) for k in ("title", "posted_local", "permalink", "age_hours", "reach", "likes",
                                            "comments", "shares", "saved", "share_rate", "save_rate")})

    # --- group averages (only posts old enough, only groups big enough)
    mature = [s for s in stats if s.get("age_hours", 0) >= MATURE_HOURS and s.get("reach") is not None and "error" not in s]
    keys = {"topic": lambda s: s.get("category"), "posting hour": lambda s: "%02d:00" % s["hour"] if "hour" in s else None,
            "slide count": lambda s: s.get("slides"), "ending style": lambda s: (s.get("tags") or {}).get("end"),
            "headline style": lambda s: (s.get("tags") or {}).get("headline")}
    groups = {}
    for name, fn in keys.items():
        buckets = defaultdict(list)
        for s in mature:
            if fn(s) is not None:
                buckets[fn(s)].append(s)
        rows = [{"key": str(k), "n": len(v), "reach": mean([x.get("reach") for x in v]),
                 "share_rate": mean([x.get("share_rate") for x in v]), "save_rate": mean([x.get("save_rate") for x in v])}
                for k, v in buckets.items() if len(v) >= MIN_GROUP]
        if len(rows) >= 2:
            groups[name] = sorted(rows, key=lambda r: -(r["share_rate"] or 0))

    # --- followers
    followers = []
    log = ROOT / "state" / "followers.csv"
    if log.exists():
        for row in list(csv.reader(log.open()))[1:]:
            if len(row) >= 3 and row[1].isdigit():
                followers.append({"date": row[0], "followers": int(row[1]), "media": int(row[2] or 0)})

    # --- alerts that don't depend on the clock (the page adds live ones itself)
    alerts = []
    if config.get("paused"):
        alerts.append({"level": "warning", "text": "Publishing is paused (config.json). Nothing will be posted."})
    if datetime.now(tz).hour >= 7 and not today_posts:
        alerts.append({"level": "critical", "text": "No posts were queued today. The daily research run did not deliver."})
    for t in today_posts:
        if t["status"] in ("failed", "rejected"):
            alerts.append({"level": "serious", "text": '"%s" did not go out: %s' % (t["title"], t["error"] or t["status"])})
    if followers and (today - datetime.strptime(followers[-1]["date"], "%Y-%m-%d").date()).days > 2:
        alerts.append({"level": "warning", "text": "Statistics haven't updated since %s." % followers[-1]["date"]})

    # --- system facts
    unsplash = [t for t in read_json(ROOT / "state" / "unsplash_requests.json", []) if t > time.time() - 86400]
    history = [l for l in (ROOT / "state" / "history.jsonl").read_text().splitlines() if l.strip()] if (ROOT / "state" / "history.jsonl").exists() else []
    slot_times = [config["post_times"][s - 1] for s in config.get("active_slots", [])]
    return {
        "account": config.get("account_name", "Account") + " " + config.get("handle", ""),
        "today_date": today.isoformat(), "today": today_posts, "posts": posts, "groups": groups,
        "mature_count": len(mature), "followers": followers, "alerts": alerts,
        "system": {"paused": bool(config.get("paused")), "posts_per_day": config["posts_per_day"], "slot_times": slot_times,
                   "last_mac_ping_utc": record_mac_ping(now), "history_count": len(history),
                   "unsplash_used": len(unsplash), "unsplash_cap": config.get("unsplash_max_requests_per_day", 100)},
    }


def main():
    now = datetime.now(timezone.utc)
    data = build(now)
    old = None
    if OUT.exists():
        m = MARK.search(OUT.read_text())
        try:
            old = json.loads(m.group(1)) if m else None
        except Exception:
            old = None
    template = (ROOT / "templates" / "dashboard.html").read_text()
    design_same = OUT.exists() and MARK.sub("", OUT.read_text(), count=1) == MARK.sub("", template, count=1)
    same = design_same and old is not None and {k: v for k, v in old.items() if k != "generated_at"} == data
    fresh = old is not None and now - datetime.fromisoformat(old["generated_at"]) < timedelta(minutes=REFRESH_MINUTES)
    if same and fresh:
        print("Dashboard unchanged.")
        return
    data["generated_at"] = now.isoformat()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(MARK.sub(lambda _: "/*DATA*/" + json.dumps(data, ensure_ascii=False) + "/*END*/", template, count=1))
    (OUT.parent / ".nojekyll").write_text("")
    print("Dashboard written:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
