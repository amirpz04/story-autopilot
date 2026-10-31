"""Render the Reel for one post on GitHub's servers and store it. Run by the Reel workflow.

Usage: python scripts/reel_job.py POST_ID

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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_reel  # noqa: E402

REELS = ROOT / "state" / "reels.json"
KEEP = 12
LIMIT_BYTES = 18_000_000   # jsDelivr serves files up to 20 MB


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def main():
    post_id = sys.argv[1]
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    post_dir = next((p.parent for p in (ROOT / "queue").glob("*/*/post.json") if json.loads(p.read_text()).get("id") == post_id), None)
    if not post_dir:
        print("Post not found:", post_id)
        return
    music, credit = make_reel.pick_music()
    work = Path(tempfile.mkdtemp())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = "%s-%s.mp4" % (stamp, post_id)
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
    files = sorted(site.glob("*.mp4"))
    for old in files[:-KEEP]:
        old.unlink()
    kept = {f.name for f in site.glob("*.mp4")}
    git(site, "checkout", "-q", "--orphan", "fresh")
    git(site, "add", "-A")
    git(site, "-c", "user.name=publisher", "-c", "user.email=publisher@users.noreply.github.com", "commit", "-q", "-m", "reels")
    git(site, "push", "-q", "-f", "origin", "fresh:reels")
    sha = git(site, "rev-parse", "HEAD")

    try:
        reels = json.loads(REELS.read_text())
    except Exception:
        reels = {}
    for pid, entry in reels.items():                      # point older reels at the new commit; forget pruned ones
        if entry.get("file") in kept:
            entry["raw_url"] = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, entry["file"])
            entry["url"] = "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, sha, entry["file"])
        elif entry.get("status") != "posted":
            entry.pop("url", None)
            entry.pop("raw_url", None)
            entry["status"] = "expired"
    reels[post_id] = {"file": name, "status": "made", "made_at": datetime.now(timezone.utc).isoformat(),
                      "music": music.name if music else "", "credit": credit,
                      "raw_url": "https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, name),
                      "url": "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, sha, name)}
    REELS.write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")
    print("Stored on the reels branch:", sha[:10])


if __name__ == "__main__":
    main()
