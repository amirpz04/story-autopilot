"""Collect Instagram statistics for our posts and write a short learning report.

Read-only: this script never posts, deletes or changes anything on Instagram, and
never touches the queue. A failure here cannot affect publishing.

Writes: state/stats.json (per post), state/report.md (summary), state/followers.csv (daily).
Environment: IG_USER_ID, IG_ACCESS_TOKEN
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
METRICS = "reach,likes,comments,shares,saved,total_interactions,views"
MATURE_HOURS = 48          # numbers before this age are still changing
MIN_GROUP = 3              # don't show a group average from fewer posts than this


def graph(path, config, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    url = "https://%s/%s/%s?%s" % (config.get("graph_host", "graph.instagram.com"), config["graph_api_version"],
                                   path, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError("HTTP %s: %s" % (exc.code, exc.read().decode()[:200]))


def load_posts():
    posts = []
    for path in ROOT.glob("queue/*/*/post.json"):
        try:
            posts.append(json.loads(path.read_text()))
        except Exception:
            pass
    return posts


def ratio(num, den):
    return round(num / den, 4) if den else None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def pct(x):
    return "-" if x is None else "%.1f%%" % (x * 100)


def collect(config):
    user = os.environ["IG_USER_ID"]
    tz = ZoneInfo(config["timezone"])
    now = datetime.now(timezone.utc)
    posts = load_posts()
    media = graph(user + "/media", config, limit=50,
                  fields="id,caption,timestamp,permalink,media_type,like_count,comments_count")["data"]
    entries = []
    for m in media:
        caption = (m.get("caption") or "").strip()
        post = next((p for p in posts if caption.startswith(p["caption"].strip()[:60])), None)
        when = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        entry = {
            "media_id": m["id"], "permalink": m.get("permalink"),
            "id": post["id"] if post else None,
            "title": post["title"] if post else caption[:60],
            "category": post.get("category") if post else None,
            "slot": post.get("slot") if post else None,
            "slides": len(post["slides"]) if post else None,
            "tags": post.get("tags", {}) if post else {},
            "posted_local": when.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "hour": when.astimezone(tz).hour,
            "age_hours": round((now - when).total_seconds() / 3600, 1),
        }
        try:
            if entry["age_hours"] > 24 * 30:
                raise RuntimeError("older than 30 days: numbers no longer change much, not re-read")
            data = graph(m["id"] + "/insights", config, metric=METRICS)["data"]
            entry.update({d["name"]: d["values"][0]["value"] for d in data})
        except Exception as exc:
            entry["error"] = str(exc)[:150]
        reach = entry.get("reach") or 0
        entry["share_rate"] = ratio(entry.get("shares", 0), reach)
        entry["save_rate"] = ratio(entry.get("saved", 0), reach)
        entry["interaction_rate"] = ratio(entry.get("total_interactions", 0), reach)
        entries.append(entry)
    return entries


def group_table(entries, label, key):
    groups = defaultdict(list)
    for e in entries:
        k = key(e)
        if k is not None:
            groups[k].append(e)
    rows = [(k, g) for k, g in groups.items() if len(g) >= MIN_GROUP]
    if len(rows) < 2:
        return ""
    out = ["", "### By %s" % label, "", "| %s | posts | avg reach | shares/reach | saves/reach |" % label, "|---|---|---|---|---|"]
    for k, g in sorted(rows, key=lambda kg: -(mean([e["share_rate"] for e in kg[1]]) or 0)):
        out.append("| %s | %d | %.0f | %s | %s |" % (k, len(g), mean([e.get("reach") for e in g]) or 0,
                                                      pct(mean([e["share_rate"] for e in g])), pct(mean([e["save_rate"] for e in g]))))
    return "\n".join(out)


def build_report(entries, followers):
    mature = [e for e in entries if e["age_hours"] >= MATURE_HOURS and "error" not in e and e.get("reach") is not None]
    lines = ["# Instagram results", "",
             "Updated %s UTC. Followers: %s. Posts tracked: %d (%d older than %d h)." % (
                 datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), followers, len(entries), len(mature), MATURE_HOURS), ""]
    if len(mature) < 15:
        lines += ["**Small sample (%d mature posts): treat everything below as noise, not as a trend.**" % len(mature), ""]
    lines += ["## Posts, best first (shares per reach is the signal Instagram weights most)", "",
              "| posted | title | category | slides | reach | shares | saves | comments | shares/reach | saves/reach | age h |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in sorted(entries, key=lambda e: -(e["share_rate"] or 0)):
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            e["posted_local"], (e["title"] or "")[:50], e["category"] or "-", e["slides"] or "-", e.get("reach", "-"),
            e.get("shares", "-"), e.get("saved", "-"), e.get("comments", "-"), pct(e["share_rate"]), pct(e["save_rate"]), e["age_hours"]))
    for label, key in (("category", lambda e: e["category"]),
                       ("posting hour", lambda e: "%02d:00" % e["hour"]),
                       ("slide count", lambda e: e["slides"]),
                       ("lane", lambda e: e["tags"].get("lane")),
                       ("ending style", lambda e: e["tags"].get("end")),
                       ("headline style", lambda e: e["tags"].get("headline"))):
        lines.append(group_table(mature, label, key))
    return "\n".join(l for l in lines if l is not None) + "\n"


def main():
    config = json.loads((ROOT / "config.json").read_text())
    try:
        entries = collect(config)
        account = graph(os.environ["IG_USER_ID"], config, fields="followers_count,media_count")
    except Exception as exc:
        print("Could not read Instagram statistics:", exc)
        sys.exit(1)

    (ROOT / "state" / "stats.json").write_text(json.dumps(entries, indent=2) + "\n")
    (ROOT / "state" / "report.md").write_text(build_report(entries, account.get("followers_count")))

    today = datetime.now(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d")
    log = ROOT / "state" / "followers.csv"
    rows = list(csv.reader(log.open())) if log.exists() else [["date", "followers", "media_count"]]
    if not any(r[0] == today for r in rows[1:]):
        rows.append([today, account.get("followers_count"), account.get("media_count")])
        csv.writer(log.open("w", newline="")).writerows(rows)
    print("Saved stats for %d posts; followers: %s" % (len(entries), account.get("followers_count")))


if __name__ == "__main__":
    main()
