"""Publish a Reel that was made for a post (state/reels.json) to Instagram. Called by control.py (post_reel).

Uses the same safety checks as normal posts (minimum gap, daily cap, Instagram's own recent posts, backoff).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publish  # noqa: E402

REELS = ROOT / "state" / "reels.json"


def post_reel(post_id):
    try:
        reels = json.loads(REELS.read_text())
    except Exception:
        reels = {}
    entry = reels.get(post_id)
    if not entry or not entry.get("raw_url"):
        return "No Reel has been made for this post yet. Press Make Reel first."
    if entry.get("status") == "posted":
        return "This Reel is already live."
    config = publish.load_config()
    wait = publish.api_backoff()
    if wait:
        return "Instagram refused requests recently; waiting until %s UTC before trying again." % wait["until"][11:16]
    path = next((p for p in (ROOT / "queue").glob("*/*/post.json") if json.loads(p.read_text()).get("id") == post_id), None)
    post = json.loads(path.read_text())
    gate = publish.instagram_gate(config, post, check_duplicate=False)
    if gate:
        return "Not posted: " + gate
    tags = [t for t in post.get("hashtags", []) if t.lower() not in post["caption"].lower()]
    caption = post["caption"].rstrip() + ("\n\n" + " ".join(tags) if tags else "")
    if entry.get("credit"):
        caption += "\n\n" + entry["credit"]
    user = os.environ["IG_USER_ID"]
    try:
        container = publish.graph("POST", user + "/media", config, media_type="REELS", video_url=entry["raw_url"],
                                  caption=caption, share_to_feed="true")["id"]
        publish.wait_until_ready(container, config)
        media_id = publish.graph("POST", user + "/media_publish", config, creation_id=container)["id"]
        permalink = publish.graph("GET", media_id, config, fields="permalink").get("permalink")
    except Exception as exc:
        if "Instagram API error" in str(exc):
            publish.note_api_failure(exc)
        return "Reel not posted: %s" % str(exc)[:200]
    entry.update(status="posted", media_id=media_id, permalink=permalink, posted_at=datetime.now(timezone.utc).isoformat())
    REELS.write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")
    return "Reel posted: %s" % (permalink or media_id)
