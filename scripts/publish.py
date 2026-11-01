"""Publish the next due post to Instagram.

Run every ~30 minutes by GitHub Actions. Each run publishes at most one post:
the earliest post for today whose publishing time has passed and that hasn't
been posted yet.

    python scripts/publish.py --check     # print the due post's folder (or nothing) and exit
    python scripts/publish.py             # render + publish the due post
    python scripts/publish.py --dry-run   # render + upload images, skip Instagram

Environment: IG_USER_ID, IG_ACCESS_TOKEN, GITHUB_TOKEN, GITHUB_REPOSITORY.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import load_config, render_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "posted.json"
MAX_ATTEMPTS = 3
HEALTH_FILE = STATE_FILE.parent / "api_health.json"


def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def api_backoff():
    """If Instagram refused us recently, return when we may try again (so we never keep hammering it)."""
    try:
        h = json.loads(HEALTH_FILE.read_text())
        until = datetime.fromisoformat(h["until"]) if h.get("until") else None
    except Exception:
        return None
    return h if until and until > datetime.now(timezone.utc) else None


def note_api_failure(reason):
    """Wait 30 min after the first refusal, then 1 h, 2 h, up to 4 h between tries."""
    try:
        fails = json.loads(HEALTH_FILE.read_text()).get("fails", 0) + 1
    except Exception:
        fails = 1
    minutes = min(240, 30 * 2 ** (fails - 1))
    HEALTH_FILE.write_text(json.dumps({"fails": fails, "reason": str(reason)[:200],
                                        "until": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()}) + "\n")


def note_api_ok():
    if HEALTH_FILE.exists():
        HEALTH_FILE.write_text(json.dumps({"fails": 0, "reason": "", "until": None}) + "\n")


def block_reason(config, state):
    """Why publishing must not happen right now, or None."""
    if config.get("paused"):
        return "publishing is paused in config.json"
    today = datetime.now(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d")
    done = sum(1 for pid, r in state.items() if pid.startswith(today) and r.get("status") == "posted")
    cap = config.get("max_posts_per_day", config["posts_per_day"])
    if done >= cap:
        return "daily cap reached (%d of %d posts)" % (done, cap)
    return None


def instagram_quota_used(config):
    """Instagram's own count of API posts in the last 24h, or None if it can't be read."""
    try:
        data = graph("GET", os.environ["IG_USER_ID"] + "/content_publishing_limit", config, fields="quota_usage")
        return data["data"][0]["quota_usage"]
    except Exception:
        return None


def instagram_gate(config, post, check_duplicate=True):
    """Safety checks against Instagram's OWN record of what is live, independent of our saved state.

    Returns None if posting is allowed, otherwise a reason string. This stops double posts
    and bursts even if state/posted.json was lost (for example a failed git push).
    Fails closed: if Instagram can't be read, we don't post this round.
    """
    try:
        media = graph("GET", os.environ["IG_USER_ID"] + "/media", config, fields="timestamp,caption", limit=25)["data"]
    except Exception as exc:
        note_api_failure(exc)
        return "cannot read recent Instagram posts, skipping to be safe (%s)" % str(exc)[:150]
    note_api_ok()
    now = datetime.now(timezone.utc)
    live = [(datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z"), (m.get("caption") or "").strip()) for m in media]
    hook = post["caption"].strip()[:60]
    if check_duplicate and any(caption.startswith(hook) for _, caption in live):
        return "already live: this post is already on Instagram"
    gap = config.get("min_minutes_between_posts", 45)
    if any(now - t < timedelta(minutes=gap) for t, _ in live):
        return "too soon: a post went out less than %d minutes ago" % gap
    cap = config.get("max_posts_per_day", config["posts_per_day"])
    last_day = sum(1 for t, _ in live if now - t < timedelta(hours=24))
    if last_day >= cap:
        return "daily cap: Instagram shows %d posts in the last 24 hours (limit %d)" % (last_day, cap)
    return None


def slot_time(config, day, slot, kind="post"):
    """Today's posting time for a slot: the base time from config.json shifted by a random
    but repeatable number of minutes (seeded by the date, so every run agrees). kind is "post" or "reel"."""
    times = config["reel_times"] if kind == "reel" else config["post_times"]
    hour, minute = map(int, times[slot - 1].split(":"))
    jitter = config.get("time_jitter_minutes", 0)
    offset = random.Random("%s-%s%d" % (day.isoformat(), "R" if kind == "reel" else "", slot)).randint(-jitter, jitter)
    base = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(config["timezone"]))
    return base + timedelta(minutes=offset)


def find_due_post(config, state):
    now = datetime.now(ZoneInfo(config["timezone"]))
    day_dir = ROOT / "queue" / now.strftime("%Y-%m-%d")

    def wanted_now(record):
        """The owner asked for this post to go out now, or at a time that has arrived."""
        if record.get("post_now"):
            return True
        return bool(record.get("post_at")) and datetime.fromisoformat(record["post_at"]) <= now

    due = []
    for path in sorted(day_dir.glob("*/post.json")):
        post = json.loads(path.read_text())
        record = state.get(post["id"], {})
        if post.get("spare") or post.get("slot") is None or record.get("status") == "posted" or record.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        if record.get("post_at"):
            is_due = wanted_now(record)
        else:
            is_due = bool(record.get("post_now")) or now >= slot_time(config, now.date(), post["slot"])
        if is_due:
            due.append((0 if wanted_now(record) else 1, post["slot"] or 0, path.parent, post))
    # Posts of other days that were sent "now" or rescheduled from the control panel.
    wanted = {pid for pid, r in state.items()
              if r.get("status") != "posted" and r.get("attempts", 0) < MAX_ATTEMPTS and wanted_now(r)}
    for path in (ROOT / "queue").glob("*/*/post.json") if wanted else []:
        if path.parent.parent == day_dir or path.parent.parent.name in ("demo", "sample"):
            continue
        post = json.loads(path.read_text())
        if post["id"] in wanted and not post.get("spare") and post.get("slot") is not None:
            due.append((0, post["slot"] or 0, path.parent, post))
    return min(due, key=lambda d: d[:2])[2:] if due else (None, None)


def find_due_reel(config, state):
    """The earliest Reel whose time has come and that isn't live (or given up on) yet.

    Two sources: (1) today's stories that have a `reel_slot`; (2) Reels of older posts that have an explicit
    `post_at` time in state/reels.json (the backlog: posts that went out before Reels existed).
    """
    import publish_reel
    now = datetime.now(ZoneInfo(config["timezone"]))
    reels = publish_reel.load_reels()
    due = []
    for path in sorted((ROOT / "queue" / now.strftime("%Y-%m-%d")).glob("*/post.json")):
        post = json.loads(path.read_text())
        if post.get("spare") or post.get("reel_slot") is None:
            continue
        if state.get(post["id"], {}).get("status") in ("removed", "deleted"):
            continue
        entry = reels.get(post["id"], {})
        if entry.get("status") in ("posted", "cancelled") or entry.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        when = slot_time(config, now.date(), post["reel_slot"], "reel")
        if now >= when:
            due.append((when, path.parent, post))
    for pid, entry in reels.items():
        if not entry.get("post_at") or entry.get("status") in ("posted", "cancelled", "failed") or entry.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        when = datetime.fromisoformat(entry["post_at"]).astimezone(now.tzinfo)
        if when > now:
            continue
        path = next((q for q in (ROOT / "queue").glob("*/*/post.json") if json.loads(q.read_text()).get("id") == pid), None)
        if path:
            due.append((when, path.parent, json.loads(path.read_text())))
    return min(due, key=lambda d: d[0]) if due else (None, None, None)


def upload_images(paths):
    """Force-push the slides to an orphan 'media' branch and return public URLs.

    The branch is replaced on every post, so images never pile up in the repo.
    """
    repo = os.environ["GITHUB_REPOSITORY"]
    remote = "https://x-access-token:%s@github.com/%s.git" % (os.environ["GITHUB_TOKEN"], repo)
    work = Path(tempfile.mkdtemp())
    for path in paths:
        shutil.copy(path, work / path.name)
    git = lambda *args: subprocess.run(["git", *args], cwd=work, check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "media")
    git("-c", "user.name=publisher", "-c", "user.email=publisher@users.noreply.github.com", "add", ".")
    git("-c", "user.name=publisher", "-c", "user.email=publisher@users.noreply.github.com", "commit", "-q", "-m", "media")
    git("push", "-q", "--force", remote, "media")
    sha = git("rev-parse", "HEAD").stdout.strip()
    return ["https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, p.name) for p in paths]


def graph(method, path, config, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    url = "https://%s/%s/%s" % (config.get("graph_host", "graph.instagram.com"), config["graph_api_version"], path)
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Instagram API error %s on %s: %s" % (exc.code, path, exc.read().decode()))


def wait_until_ready(container_id, config):
    for _ in range(30):
        status = graph("GET", container_id, config, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError("container %s failed with status %s" % (container_id, status))
        time.sleep(5)
    raise RuntimeError("container %s not ready after 150s" % container_id)


def publish_to_instagram(image_urls, caption, config):
    user = os.environ["IG_USER_ID"]
    if len(image_urls) == 1:
        container = graph("POST", user + "/media", config, image_url=image_urls[0], caption=caption)["id"]
    else:
        children = [
            graph("POST", user + "/media", config, image_url=url, is_carousel_item="true")["id"]
            for url in image_urls
        ]
        for child in children:
            wait_until_ready(child, config)
        container = graph(
            "POST", user + "/media", config,
            media_type="CAROUSEL", children=",".join(children), caption=caption,
        )["id"]
    wait_until_ready(container, config)
    return graph("POST", user + "/media_publish", config, creation_id=container)["id"]


def main():
    config = load_config()
    state = load_state()
    reason = block_reason(config, state)
    if reason:
        print("Not publishing:", reason, file=sys.stderr)
    post_dir, post = (None, None) if reason else find_due_post(config, state)
    reel_when, reel_dir, reel_post = (None, None, None) if reason else find_due_reel(config, state)
    # one thing per run: the Reel only if it is due earlier than the carousel (or no carousel is due)
    reel_first = reel_post is not None and (post is None or reel_when < slot_time(config, datetime.now(ZoneInfo(config["timezone"])).date(), post["slot"] or 1))

    if "--check" in sys.argv:
        chosen = reel_dir if reel_first else post_dir
        print(chosen.relative_to(ROOT) if chosen else "")
        return
    if reel_first:
        wait = api_backoff()
        if wait:
            print("Waiting: Instagram refused requests earlier. Next try after %s UTC." % wait["until"][11:16])
            return
        import publish_reel
        print("Publishing the Reel of", reel_post["id"], "-", reel_post["title"])
        print(publish_reel.publish_due_reel(reel_post["id"]))
        return
    if not post:
        print("Nothing due.")
        return

    wait = api_backoff()
    if wait:
        print("Waiting: Instagram refused requests earlier (%s). Next try after %s UTC." % (wait.get("reason", "")[:80], wait["until"][11:16]))
        return

    gate = instagram_gate(config, post)
    if gate:
        print("Not publishing:", gate)
        if gate.startswith("already live"):
            state.setdefault(post["id"], {"attempts": 0}).update(status="posted", note="found live on Instagram")
            save_state(state)
        return

    delay = random.randint(0, config.get("publish_random_delay_seconds", 0))
    if delay:
        print("Waiting %d seconds so the posting time isn't exact..." % delay)
        time.sleep(delay)
    print("Publishing", post["id"], "-", post["title"])
    record = state.setdefault(post["id"], {"attempts": 0})
    record["attempts"] += 1
    try:
        used = instagram_quota_used(config)
        if used is not None and used >= config.get("ig_quota_stop", 25):
            raise RuntimeError("Instagram reports %d API posts in the last 24h; stopping at %d" % (used, config.get("ig_quota_stop", 25)))
        paths = render_post(post_dir, Path(tempfile.mkdtemp()), config)
        urls = upload_images(paths)
        tags = [t for t in post.get("hashtags", []) if t.lower() not in post["caption"].lower()]
        caption = post["caption"].rstrip() + ("\n\n" + " ".join(tags) if tags else "")
        if "--dry-run" in sys.argv:
            print("Dry run, images at:", *urls, sep="\n  ")
            state.pop(post["id"])
            return
        media_id = publish_to_instagram(urls, caption, config)
        record.update(status="posted", media_id=media_id, posted_at=datetime.utcnow().isoformat() + "Z")
        print("Posted, media id", media_id)
    except Exception as exc:
        if "Instagram API error" in str(exc):
            note_api_failure(exc)
        record.update(status="failed", error=str(exc)[:500])
        print("FAILED:", exc)
        raise
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
