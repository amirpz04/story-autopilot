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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import load_config, render_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "posted.json"
MAX_ATTEMPTS = 3


def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


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


def find_due_post(config, state):
    now = datetime.now(ZoneInfo(config["timezone"]))
    day_dir = ROOT / "queue" / now.strftime("%Y-%m-%d")
    due = []
    for path in sorted(day_dir.glob("*/post.json")):
        post = json.loads(path.read_text())
        record = state.get(post["id"], {})
        if record.get("status") == "posted" or record.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        hour, minute = map(int, config["post_times"][post["slot"] - 1].split(":"))
        if now >= now.replace(hour=hour, minute=minute, second=0, microsecond=0):
            due.append((post["slot"], path.parent, post))
    return min(due, key=lambda d: d[0])[1:] if due else (None, None)


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

    if "--check" in sys.argv:
        print(post_dir.relative_to(ROOT) if post_dir else "")
        return
    if not post:
        print("Nothing due.")
        return

    print("Publishing", post["id"], "-", post["title"])
    record = state.setdefault(post["id"], {"attempts": 0})
    record["attempts"] += 1
    try:
        used = instagram_quota_used(config)
        if used is not None and used >= config.get("ig_quota_stop", 25):
            raise RuntimeError("Instagram reports %d API posts in the last 24h; stopping at %d" % (used, config.get("ig_quota_stop", 25)))
        paths = render_post(post_dir, Path(tempfile.mkdtemp()), config)
        urls = upload_images(paths)
        caption = post["caption"] + "\n\n" + " ".join(post.get("hashtags", []))
        if "--dry-run" in sys.argv:
            print("Dry run, images at:", *urls, sep="\n  ")
            state.pop(post["id"])
            return
        media_id = publish_to_instagram(urls, caption, config)
        record.update(status="posted", media_id=media_id, posted_at=datetime.utcnow().isoformat() + "Z")
        print("Posted, media id", media_id)
    except Exception as exc:
        record.update(status="failed", error=str(exc)[:500])
        print("FAILED:", exc)
        raise
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
