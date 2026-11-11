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
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
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


def reel_time(config, day, post, reel):
    """When this post's Reel goes out (UTC ISO): its explicit time if it has one, otherwise its Reel slot of that day."""
    if reel and reel.get("post_at"):
        return reel["post_at"]
    if post.get("reel_slot") is not None:
        return publish.slot_time(config, day, post["reel_slot"], "reel").astimezone(timezone.utc).isoformat()
    return None


def hooks_by_id():
    """The cover headline of every queued story: the line viewers actually read (the internal title is only a label)."""
    out = {}
    for path in (ROOT / "queue").glob("*/*/post.json"):
        try:
            post = json.loads(path.read_text())
            out[post["id"]] = (post["slides"][0].get("headline") or "").strip()
        except Exception:
            pass
    return out


def music_list():
    meta = read_json(ROOT / "assets" / "music" / "music.json", {})
    out = []
    for name, m in sorted(meta.items(), key=lambda kv: kv[1].get("added", ""), reverse=True):
        if (ROOT / "assets" / "music" / name).exists():
            out.append(dict(m, file=name, url="https://cdn.jsdelivr.net/gh/amirpz04/story-autopilot@main/assets/music/" + name))
    used = read_json(ROOT / "state" / "music_log.json", [])
    for m in out:
        m["uses"] = sum(1 for u in used if Path(u).stem == Path(m["file"]).stem)
    return out


def build(now):
    config = publish.load_config()
    tz = ZoneInfo(config["timezone"])
    today = datetime.now(tz).date()
    posted = read_json(ROOT / "state" / "posted.json", {})
    stats = read_json(ROOT / "state" / "stats.json", [])
    by_id = {s["id"]: s for s in stats if s.get("id") and s.get("kind") != "reel"}
    reel_stats = {s["id"]: s for s in stats if s.get("id") and s.get("kind") == "reel"}
    reels = read_json(ROOT / "state" / "reels.json", {})

    # --- today's queue
    today_posts = []
    for path in sorted((ROOT / "queue" / today.isoformat()).glob("*/post.json")):
        post = json.loads(path.read_text())
        if post.get("slot") is None:
            continue
        rec = posted.get(post["id"], {})
        today_posts.append({
            "id": post["id"], "title": post["title"], "category": post.get("category", ""), "slot": post["slot"],
            "scheduled_utc": rec.get("post_at") or publish.slot_time(config, today, post["slot"]).astimezone(timezone.utc).isoformat(),
            "status": rec.get("status"), "error": rec.get("error"), "posted_at": rec.get("posted_at"),
            "permalink": by_id.get(post["id"], {}).get("permalink"),
        })

    # --- every post of the last 3 weeks, with slides and caption, for the Posts page
    all_posts, cutoff = [], today - timedelta(days=21)
    for path in sorted((ROOT / "queue").glob("*/*/post.json"), reverse=True):
        try:
            day = date.fromisoformat(path.parent.parent.name)
        except ValueError:
            # demo / sample folders: only posts that are really live (or have a planned Reel) are shown, on the day they went live
            pid = (read_json(path, {}) or {}).get("id")
            live_entry = by_id.get(pid)
            if not live_entry and pid not in reels:
                continue
            day = date.fromisoformat((live_entry or {}).get("posted_local", today.isoformat())[:10])
        if day < cutoff:
            continue
        post = json.loads(path.read_text())
        rec, st = posted.get(post["id"], {}), by_id.get(post["id"], {})
        reel = reels.get(post["id"])
        rs = reel_stats.get(post["id"], {})
        all_posts.append({
            "post_at": rec.get("post_at"),
            "reel_slot": post.get("reel_slot"), "has_slot": post.get("slot") is not None,
            "reel_scheduled_utc": reel_time(config, day, post, reel),
            "reel_date": (lambda t: datetime.fromisoformat(t).astimezone(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d") if t else None)(reel_time(config, day, post, reel)),
            "reel": ({k: reel.get(k) for k in ("status", "url", "made_at", "music", "permalink", "posted_at", "attempts", "error", "post_at", "backfill") if k in reel} if reel else None),
            "reel_stats": {k: rs.get(k) for k in ("reach", "likes", "comments", "shares", "saved", "views", "share_rate")} if rs else None,
            "id": post["id"], "date": day.isoformat(), "slot": post["slot"], "title": post["title"],
            "hook": (post["slides"][0].get("headline") or "").strip(),
            "category": post.get("category", ""), "lane": (post.get("tags") or {}).get("lane", ""),
            "status": rec.get("status") or ("posted" if st else None), "post_now": bool(rec.get("post_now")), "error": rec.get("error"),
            "scheduled_utc": None if post.get("slot") is None else (rec.get("post_at") or publish.slot_time(config, day, post["slot"]).astimezone(timezone.utc).isoformat()),
            "posted_at": rec.get("posted_at"), "permalink": st.get("permalink"), "media_id": rec.get("media_id") or st.get("media_id"),
            "slides": [{"type": sl.get("type"), "layout": sl.get("layout"), "kicker": sl.get("kicker"),
                        "text": sl.get("headline") or sl.get("text"),
                        "image": (sl.get("image") or {}).get("url"), "credit": (sl.get("image") or {}).get("credit")}
                       for sl in post["slides"]],
            "caption": post.get("caption", ""), "hashtags": post.get("hashtags", []),
            "sources": post.get("sources", []), "verification": post.get("verification", ""),
            "stats": {k: st.get(k) for k in ("reach", "likes", "comments", "shares", "saved", "share_rate", "save_rate")} if st else None,
        })
    known = {p["id"] for p in all_posts}
    for s in stats:  # live posts that aren't in the recent queue (e.g. early test posts)
        if s.get("id") not in known and s.get("kind") != "reel":
            all_posts.append({"id": s.get("id") or s.get("media_id"), "date": (s.get("posted_local") or "")[:10], "slot": None,
                              "title": s.get("title"), "category": s.get("category") or "", "lane": (s.get("tags") or {}).get("lane", ""),
                              "status": "posted", "posted_local": s.get("posted_local"), "permalink": s.get("permalink"),
                              "media_id": s.get("media_id"), "slides": [], "caption": "", "hashtags": [], "sources": [],
                              "stats": {k: s.get(k) for k in ("reach", "likes", "comments", "shares", "saved", "share_rate", "save_rate")}})

    # --- posts on Instagram, newest first
    hooks = hooks_by_id()
    posts = []
    for s in sorted(stats, key=lambda s: s.get("posted_local", ""), reverse=True):
        entry = {k: s.get(k) for k in ("id", "kind", "title", "category", "posted_local", "hour", "permalink", "age_hours", "reach",
                                       "views", "likes", "comments", "shares", "saved", "total_interactions", "share_rate", "save_rate")}
        entry["hook"] = hooks.get(s.get("id"), "")
        posts.append(entry)

    # --- group averages (only posts old enough, only groups big enough)
    mature = [s for s in stats if s.get("age_hours", 0) >= MATURE_HOURS and s.get("reach") is not None and "error" not in s]
    keys = {"topic": lambda s: s.get("category"), "posting hour": lambda s: "%02d:00" % s["hour"] if "hour" in s else None,
            "lane": lambda s: (s.get("tags") or {}).get("lane"), "slide count": lambda s: s.get("slides"), "ending style": lambda s: (s.get("tags") or {}).get("end"),
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
    # Reel-only stories have no carousel slot, so check for ANY story queued today (with 0 carousels a day this always fired)
    if datetime.now(tz).hour >= 7 and not any((ROOT / "queue" / today.isoformat()).glob("*/post.json")):
        alerts.append({"level": "critical", "text": "No posts were queued today. The daily research run did not deliver."})
    if followers and (today - datetime.strptime(followers[-1]["date"], "%Y-%m-%d").date()).days > 2:
        alerts.append({"level": "warning", "text": "Statistics haven't updated since %s." % followers[-1]["date"]})

    # Anything of the last days whose time passed and that is not live: say so, with Instagram's or the renderer's error.
    recent = (today - timedelta(days=publish.CATCH_UP_DAYS)).isoformat()
    def plain(error):
        if not error:
            return ""
        if "action is blocked" in error or "2207051" in error:
            return "Instagram blocked it as possible spam"
        if "Instagram API error" in error:
            m = re.search(r'"message":"([^"]+)"', error)
            return "Instagram said: " + (m.group(1) if m else error[:80])
        return error[:90]

    def missed(kind, title, due, error, tries, give_up):
        error = plain(error)
        note = (" Gave up after %d tries: needs a fix (ask Claude)." % tries) if give_up else " It is retried automatically."
        alerts.append({"level": "serious", "text": '%s "%s" was due %s UTC and is not live%s.%s' % (
            kind, title[:50], due.strftime("%b %d %H:%M"), (" (" + error[:90] + ")") if error else "", note)})
    for p in all_posts:
        if not p.get("date") or p["date"] < recent or p["date"] > today.isoformat() or p.get("status") in ("removed", "deleted"):
            continue
        if p.get("scheduled_utc") and p.get("status") != "posted":
            due = datetime.fromisoformat(p["scheduled_utc"])
            if now - due > timedelta(minutes=45):
                tries = (posted.get(p["id"]) or {}).get("attempts", 0)
                missed("Post", p["title"], due, p.get("error"), tries, tries >= publish.MAX_ATTEMPTS)
        r = p.get("reel") or {}
        if p.get("reel_scheduled_utc") and r.get("status") not in ("posted", "cancelled"):
            due = datetime.fromisoformat(p["reel_scheduled_utc"])
            if now - due > timedelta(minutes=45):
                missed("Reel", p["title"], due, r.get("error"), r.get("attempts", 0), r.get("attempts", 0) >= publish.MAX_ATTEMPTS)
    health = read_json(ROOT / "state" / "api_health.json", {})
    if health.get("until") and datetime.fromisoformat(health["until"]) > datetime.now(timezone.utc):
        alerts.append({"level": "warning", "text": "Instagram refused our last request (%s). The system is waiting until %s UTC before trying again, on purpose, so it doesn't pile up requests." % (health.get("reason", "")[:90], health["until"][11:16])})

    # --- system facts
    history = [l for l in (ROOT / "state" / "history.jsonl").read_text().splitlines() if l.strip()] if (ROOT / "state" / "history.jsonl").exists() else []
    slot_times = [config["post_times"][s - 1] for s in config.get("active_slots", [])]
    return {
        "account": config.get("account_name", "Account") + " " + config.get("handle", ""),
        "today_date": today.isoformat(), "today": today_posts, "posts": posts, "groups": groups,
        "account_now": read_json(ROOT / "state" / "account.json", {}), "music": music_list(), "all_posts": all_posts, "control_log": read_json(ROOT / "state" / "control_log.json", [])[:20],
        "repo": os.environ.get("GITHUB_REPOSITORY", "amirpz04/story-autopilot"),
        "routine_url": "https://claude.ai/code/routines/trig_015p8XY87MCPiPaEgKXrXyxf",
        "mature_count": len(mature), "followers": followers, "alerts": alerts,
        "system": {"paused": bool(config.get("paused")), "posts_per_day": config["posts_per_day"], "slot_times": slot_times,
                   "last_mac_ping_utc": record_mac_ping(now), "history_count": len(history),
                   "api_wait_until": health.get("until") if health.get("until") and datetime.fromisoformat(health["until"]) > datetime.now(timezone.utc) else None,
                   "catch_up_days": publish.CATCH_UP_DAYS, "queued_today": sum(1 for p in all_posts if p.get("date") == today.isoformat() and p.get("status") not in ("removed", "deleted")),
                   "reels_per_day": config.get("reels_per_day", 0), "reels_mode": config.get("reels_mode", "same"),
                   "stories_per_day": config.get("stories_per_day", config["posts_per_day"]),
                   "reel_times": [config["reel_times"][i - 1] for i in config.get("reel_active_slots", [])],
                   "reels_made": sum(1 for r in reels.values() if r.get("status") in ("made", "posted")),
                   "reels_planned": sum(1 for r in reels.values() if r.get("status") in ("pending", "made") and r.get("post_at")),
                   "reels_posted": sum(1 for r in reels.values() if r.get("status") == "posted")},
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
    if same and fresh and "--force" not in sys.argv:
        print("Dashboard unchanged.")
        return
    data["generated_at"] = now.isoformat()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(MARK.sub(lambda _: "/*DATA*/" + json.dumps(data, ensure_ascii=False) + "/*END*/", template, count=1))
    (OUT.parent / ".nojekyll").write_text("")
    print("Dashboard written:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
