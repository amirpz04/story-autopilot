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
MAX_ATTEMPTS = 3


def load_reels():
    try:
        return json.loads(REELS.read_text())
    except Exception:
        return {}


def save_reels(reels):
    REELS.write_text(json.dumps(reels, indent=2, sort_keys=True) + "\n")


def publish_due_reel(post_id):
    """Post a Reel at its time. If it hasn't been made yet (the early rendering failed), make it now."""
    entry = load_reels().get(post_id)
    if not entry or entry.get("status") not in ("made",) or not entry.get("raw_url"):
        import reel_job
        if not reel_job.make_one(post_id):
            return "Could not make the Reel (will try again at the next check)."
    return post_reel(post_id)


COVER_MS = 2200     # the grid thumbnail is a frame of the video: at 0 s there is only a bare picture, by 2.2 s the headline is fully shown


COVER_NOTE = {"last": ""}


def create_container(user, config, video_url, caption):
    """Start the Reel upload with the cover frame set to the moment the headline is readable. If Instagram rejects that
    one setting, try once more without it so the Reel itself is never held back; any other error is raised as before."""
    COVER_NOTE["last"] = "frame at %.1f s" % (COVER_MS / 1000)
    params = dict(media_type="REELS", video_url=video_url, caption=caption, share_to_feed="true", thumb_offset=str(COVER_MS))
    try:
        return publish.graph("POST", user + "/media", config, **params)["id"]
    except RuntimeError as exc:
        text = str(exc)
        if "thumb_offset" in text or '"code":100' in text or "Invalid parameter" in text:
            params.pop("thumb_offset")
            COVER_NOTE["last"] = "default frame (Instagram refused the cover setting)"
            return publish.graph("POST", user + "/media", config, **params)["id"]
        raise


def post_reel(post_id):
    reels = load_reels()
    entry = reels.get(post_id)
    if not entry or not entry.get("raw_url"):
        return "No Reel has been made for this post yet."
    if entry.get("status") == "posted":
        return "This Reel is already live."
    if entry.get("status") == "cancelled":
        return "This Reel was cancelled."
    config = publish.load_config()
    wait = publish.api_backoff()
    if wait:
        return "Instagram refused requests recently; waiting until %s UTC before trying again." % wait["until"][11:16]
    path = next((p for p in (ROOT / "queue").glob("*/*/post.json") if json.loads(p.read_text()).get("id") == post_id), None)
    post = json.loads(path.read_text())
    gate = publish.instagram_gate(config, post, kind="reel")
    if gate and gate.startswith("already live"):
        entry.update(status="posted", note="found live on Instagram")
        save_reels(reels)
    if gate:
        return "Not posted yet: " + gate
    tags = [t for t in post.get("hashtags", []) if t.lower() not in post["caption"].lower()]
    caption = post["caption"].rstrip() + ("\n\n" + " ".join(tags) if tags else "")
    credits = []
    for sl in post["slides"]:                      # photo credits live in the caption on Reels (the picture itself stays clean)
        c = ((sl.get("image") or {}).get("credit") or "").strip()
        if (sl.get("image") or {}).get("url") and c and c not in credits:
            credits.append(c)
    if credits:
        caption += "\n\nPhotos: " + "; ".join(credits)[:320]
    if entry.get("credit"):
        caption += "\n\n" + entry["credit"]
    user = os.environ["IG_USER_ID"]
    try:
        container = create_container(user, config, entry["raw_url"], caption)
        publish.wait_until_ready(container, config)
        media_id = publish.graph("POST", user + "/media_publish", config, creation_id=container)["id"]
        permalink = publish.graph("GET", media_id, config, fields="permalink").get("permalink")
    except Exception as exc:
        if "Instagram API error" in str(exc):
            publish.note_api_failure(exc)
        if publish.is_block(exc) and "/media_publish" in str(exc):
            entry["attempts"] = MAX_ATTEMPTS      # the Reel is probably live already; never create a second one
        else:
            entry["attempts"] = entry.get("attempts", 0) + 1
        entry["error"] = str(exc)[:200]
        save_reels(reels)
        return "Reel not posted: %s" % str(exc)[:200]
    publish.note_api_ok()
    entry["cover"] = COVER_NOTE["last"]
    entry.update(status="posted", media_id=media_id, permalink=permalink, posted_at=datetime.now(timezone.utc).isoformat(), attempts=0, error="")
    save_reels(reels)
    return "Reel posted: %s" % (permalink or media_id)
