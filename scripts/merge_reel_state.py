"""Re-apply a Reel job's results on top of the newest state/reels.json (used by reel.yml when its save collides
with another commit, for example the publisher's).

Usage: python scripts/merge_reel_state.py MINE_REELS.json MINE_MUSIC_LOG.json
MINE_* are the job's own copies. state/reels.json in the work tree is the newest one on main.
Rule: a Reel the job just made wins, unless the publisher has already posted it; for every other Reel keep the
newest record but point its video links at the job's (the `reels` branch is rewritten on every job).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    mine = json.loads(Path(sys.argv[1]).read_text())
    theirs_path = ROOT / "state" / "reels.json"
    theirs = json.loads(theirs_path.read_text())
    for pid, m in mine.items():
        t = theirs.get(pid)
        if t is None:
            theirs[pid] = m
        elif t.get("status") == "posted":
            continue                                               # already live: never touch
        elif (m.get("made_at") or "") > (t.get("made_at") or ""):
            theirs[pid] = m
        elif t.get("file") == m.get("file"):
            t["raw_url"], t["url"] = m.get("raw_url", t.get("raw_url")), m.get("url", t.get("url"))
    theirs_path.write_text(json.dumps(theirs, indent=2, sort_keys=True) + "\n")
    if len(sys.argv) > 2:
        (ROOT / "state" / "music_log.json").write_text(Path(sys.argv[2]).read_text())
    print("merged", len(mine), "records")


if __name__ == "__main__":
    main()
