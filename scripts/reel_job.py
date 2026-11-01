"""Render Reels on GitHub's servers and store them. Used by the Reel workflow and by the publisher.

Usage:
  python scripts/reel_job.py            make every Reel that today's posts need and don't have yet
  python scripts/reel_job.py POST_ID    (re)make the Reel of one post

The video goes to the repo's `reels` branch (rewritten each time, newest 12 kept, so the repo never grows);
state/reels.json records where it is. Nothing is posted to Instagram here.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_reel  # noqa: E402

REELS = ROOT / "state" / "reels.json"
POSTED = ROOT / "state" / "posted.json"
KEEP = 12
LIMIT_BYTES = 18_000_000   # jsDelivr serves files up to 20 MB


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def find_post_dir(post_id):
    for p in (ROOT / "queue").glob("*/*/post.json"):
        if load(p, {}).get("id") == post_id:
            return p.parent
    return None


def posts_needing_reels():
    """Today's posts that should become a Reel and don't have a made (or live) one yet."""
    config = load(ROOT / "config.json", {})
    today = datetime.now(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d")
    reels, posted, ids = load(REELS, {}), load(POSTED, {}), []
    for pid, e in sorted(reels.items()):                     # backlog Reels waiting to be rendered
        if e.get("status") == "pending" and e.get("attempts", 0) < 3:
            ids.append(pid)
    for path in sorted((ROOT / "queue" / today).glob("*/post.json")):
        post = load(path, {})
        if post.get("spare") or post.get("reel_slot") is None:
            continue
        if posted.get(post["id"], {}).get("status") in ("removed", "deleted"):
            continue
        if reels.get(post["id"], {}).get("status") in ("made", "posted", "cancelled") or reels.get(post["id"], {}).get("attempts", 0) >= 3:
            continue
        ids.append(post["id"])
    return ids


def make_one(post_id):
    """Render one post's Reel and store it. Returns True on success."""
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    post_dir = find_post_dir(post_id)
    if not post_dir:
        print("Post not found:", post_id)
        return False
    reels = load(REELS, {})
    attempts = reels.get(post_id, {}).get("attempts", 0) + 1
    try:
        music, credit = make_reel.pick_music()
        work = Path(tempfile.mkdtemp())
        name = "%s-%s.mp4" % (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"), post_id)
        out = work / name
        make_reel.make_reel(post_dir, out, music=music)
        if out.stat().st_size > LIMIT_BYTES:                 # squeeze if the video is too big to host
            small = work / "small.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-c:v", "libx264", "-b:v", "2800k", "-maxrate", "3500k",
                            "-bufsize", "7000k", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(small)], check=True)
            small.replace(out)
        print("Reel %s: %.1f MB, music %s" % (name, out.stat().st_size / 1e6, music.name if music else "none"))

        remote = "https://x-access-token:%s@github.com/%s.git" % (token, repo)
        site = work / "site"
        try:
            git(work, "clone", "-q", "--depth", "1", "-b", "reels", remote, str(site))
        except subprocess.CalledProcessError:            # first time: the branch doesn't exist yet
            site.mkdir()
            git(site, "init", "-q", "-b", "reels")
            git(site, "remote", "add", "origin", remote)
        shutil.copy(out, site / name)
        for old in sorted(site.glob("*.mp4"))[:-KEEP]:
            old.unlink()
        kept = {f.name for f in site.glob("*.mp4")}
        git(site, "checkout", "-q", "--orphan", "fresh")
        git(site, "add", "-A")
        git(site, "-c", "user.name=publisher", "-c", "user.email=publisher@users.noreply.github.com", "commit", "-q", "-m", "reels")
        git(site, "push", "-q", "-f", "origin", "fresh:reels")
        sha = git(site, "rev-parse", "HEAD")
    except Exception as exc:
        reels = load(REELS, {})
        reels[post_id] = dict(reels.get(post_id, {}), attempts=attempts, status="failed", error=str(exc)[:200])
        REELS.write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")
        print("Reel failed:", exc)
        return False

    reels = load(REELS, {})
    for pid, entry in reels.items():                      # point older reels at the new commit; forget pruned ones
        if entry.get("file") in kept:
            entry["raw_url"] = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, entry["file"])
            entry["url"] = "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, sha, entry["file"])
        elif entry.get("status") not in ("posted", "failed"):
            entry.pop("url", None)
            entry.pop("raw_url", None)
            entry["status"] = "expired"
    keep = {k: v for k, v in reels.get(post_id, {}).items() if k in ("backfill", "post_at")}   # a backlog Reel keeps its scheduled time
    reels[post_id] = {**keep, "file": name, "status": "made", "made_at": datetime.now(timezone.utc).isoformat(), "attempts": 0,
                      "music": music.name if music else "", "credit": credit,
                      "raw_url": "https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, name),
                      "url": "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, sha, name)}
    REELS.write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")
    print("Stored on the reels branch:", sha[:10])
    return True


def main():
    ids = [sys.argv[1]] if len(sys.argv) > 1 else posts_needing_reels()
    print("Reels to make:", ids or "none")
    for post_id in ids:
        make_one(post_id)


if __name__ == "__main__":
    main()
