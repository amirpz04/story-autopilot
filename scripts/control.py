"""Carry out one control-panel action. Run by the Control workflow (started from the dashboard).

Usage: python scripts/control.py ACTION [TARGET] [TEXT]     (TEXT may also come from the TEXT environment variable)

  pause / resume                 stop or restart all publishing
  remove POST_ID                 never publish this post (any post that isn't live; kept for the record)
  restore POST_ID                undo "remove"
  post_now POST_ID               publish at the next check, ignoring its time slot (45-minute gap and daily cap still apply)
  reschedule POST_ID  TEXT       publish at the time in TEXT (UTC, e.g. 2026-11-02T14:30:00Z); empty TEXT goes back to its normal slot
  replace POST_ID [SPARE_ID]     swap a post of today for a ready-made spare post (the newest one, or the spare named in TEXT); the old one is kept as "removed"
  edit_caption POST_ID  TEXT     change the caption of a post that isn't live
  edit_slide POST_ID#N  TEXT     change the text of slide N (1-based) of a post that isn't live
  posts_per_day N                0-5 carousel posts a day from the next research run on
  reels_per_day N                0-5 Reels a day from the next research run on (at least one post or Reel a day)
  spares_per_day N               0-3 extra spare posts the research run prepares each day (uses more Claude usage)
  delete_instagram POST_ID       delete a live post from Instagram (the whole carousel)
  post_reel POST_ID              publish the Reel that was made for this post
  add_music URL  TEXT            add a song from a direct link; TEXT = "title | credit line for the caption (empty if none needed) | license"
  remove_music FILE              delete a song from the music list
  refresh_dashboard              just rebuild the dashboard

Every action is written to state/control_log.json, which the dashboard shows. This script never exits with an
error, so nothing emails anyone; problems show up in the log.
"""
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG = ROOT / "config.json"
POSTED = ROOT / "state" / "posted.json"
STATS = ROOT / "state" / "stats.json"
LOG = ROOT / "state" / "control_log.json"
MAX_ATTEMPTS = 3
SLOTS = {0: [], 1: [3], 2: [1, 5], 3: [1, 3, 5], 4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5]}
REEL_SLOTS = {0: [], 1: [3], 2: [2, 4], 3: [1, 3, 5], 4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5]}
REELS = ROOT / "state" / "reels.json"


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_post(path, post):
    path.write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")


def post_files():
    for path in sorted((ROOT / "queue").glob("*/*/post.json")):
        if path.parent.parent.name not in ("demo", "sample"):
            yield path


def find_post(post_id):
    for path in post_files():
        post = load(path, {})
        if post.get("id") == post_id:
            return path, post
    return None, None


def find_media_id(post_id, posted):
    if posted.get(post_id, {}).get("media_id"):
        return posted[post_id]["media_id"]
    for s in load(STATS, []):
        if post_id in (s.get("id"), s.get("media_id")) and s.get("media_id"):
            return s["media_id"]
    return None


def delete_from_instagram(media_id, config):
    url = "https://%s/%s/%s?%s" % (config.get("graph_host", "graph.instagram.com"), config["graph_api_version"], media_id,
                                   urllib.parse.urlencode({"access_token": os.environ["IG_ACCESS_TOKEN"]}))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=60) as resp:
            return json.loads(resp.read() or b"{}").get("success", True), ""
    except urllib.error.HTTPError as exc:
        return False, "Instagram said %s: %s" % (exc.code, exc.read().decode()[:200])
    except Exception as exc:
        return False, str(exc)[:200]


def replace(target, config, posted, now, wanted_spare=None):
    path, post = find_post(target)
    if not path:
        return "Post not found."
    if post.get("spare"):
        return "That is a spare. Replace a scheduled post to use it."
    record = posted.get(target, {})
    if record.get("status") == "posted":
        return "That post is already live and can't be replaced."
    today = datetime.now(ZoneInfo(config["timezone"])).date()
    if path.parent.parent.name != today.isoformat():
        return "Only today's posts can be replaced. Use Remove for older ones."
    spares = []
    for p in post_files():
        sp = load(p, {})
        if not sp.get("spare") or posted.get(sp.get("id"), {}).get("status") in ("removed", "deleted"):
            continue
        if wanted_spare and sp.get("id") != wanted_spare:
            continue
        try:
            d = date.fromisoformat(p.parent.parent.name)
        except ValueError:
            continue
        if today - timedelta(days=2) <= d <= today:
            spares.append((d, sp["id"], p, sp))
    if not spares:
        return "No spare post is ready. Open the daily research run and press Run now (it prepares spares), or wait for the next run."
    _, spare_id, spare_path, spare = sorted(spares, key=lambda s: (s[0], s[1]), reverse=True)[0]
    slot, reel_slot, old_dir = post.get("slot"), post.get("reel_slot"), path.parent
    parked = old_dir.with_name(old_dir.name + "-replaced")
    n = 2
    while parked.exists():
        parked = old_dir.with_name("%s-replaced%d" % (old_dir.name, n))
        n += 1
    shutil.move(str(old_dir), str(parked))
    shutil.move(str(spare_path.parent), str(old_dir))
    spare.update(slot=slot, reel_slot=reel_slot, spare=False)
    forget_reel(target)
    forget_reel(spare_id)
    write_post(old_dir / "post.json", spare)
    posted[target] = dict(record, status="removed", attempts=MAX_ATTEMPTS, removed_at=now, replaced_by=spare_id)
    save(POSTED, posted)
    return 'Replaced with "%s". It goes out at this slot\'s time (right away if that time has passed).' % spare["title"][:70]


def forget_reel(post_id):
    """The slides changed, so a Reel that was made but not posted is out of date: drop it so it is made again."""
    reels = load(REELS, {})
    if reels.get(post_id, {}).get("status") in ("made", "failed", "expired"):
        reels.pop(post_id)
        save(REELS, reels)


def edit_post(post_id, change, config, posted, slides_changed=False):
    path, post = find_post(post_id)
    if not path:
        return "Post not found."
    if posted.get(post_id, {}).get("status") == "posted":
        return "That post is already live; it can't be edited."
    import validate
    original = path.read_text()
    before = set(validate.check_post(path, config))
    problem = change(post)
    if problem:
        return problem
    write_post(path, post)
    new_errors = [e for e in validate.check_post(path, config) if e not in before]   # only refuse what the edit itself breaks
    if new_errors:
        path.write_text(original)
        return "Not saved: " + "; ".join(new_errors[:3])
    if slides_changed:
        forget_reel(post_id)
    return "Saved." + (" Its Reel will be made again." if slides_changed and post.get("reel_slot") is not None else "")


MUSIC = ROOT / "assets" / "music"
MAX_MUSIC_BYTES = 40_000_000


def add_music(url, text):
    import re
    import subprocess
    import tempfile
    from urllib.parse import urlparse
    if not url.startswith("https://"):
        return "The link must start with https:// and point straight to an audio file (.mp3, .ogg, .wav, .m4a)."
    parts = [p.strip() for p in (text or "").split("|")]
    title, credit, lic = (parts + ["", "", ""])[:3]
    stem = Path(urlparse(url).path).stem
    title = title or re.sub(r"[_\-]+", " ", stem).strip()[:60] or "Untitled"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "track"
    out = MUSIC / (slug + ".m4a")
    if out.exists():
        return "A song named %s already exists. Pick another title." % out.name
    tmp = Path(tempfile.mkdtemp()) / "src"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StoryAccountBot/1.0 (music)"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read(MAX_MUSIC_BYTES + 1)
    except Exception as exc:
        return "Couldn't download that link: %s" % str(exc)[:120]
    if len(data) > MAX_MUSIC_BYTES:
        return "That file is larger than 40 MB."
    tmp.write_bytes(data)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(tmp)], capture_output=True, text=True)
    try:
        info = json.loads(probe.stdout)
        seconds = float(info["format"]["duration"])
        assert any(st.get("codec_type") == "audio" for st in info["streams"])
    except Exception:
        return "That link isn't an audio file I can read."
    if seconds < 20:
        return "That track is only %d seconds; Reels need at least 20." % seconds
    done = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-vn", "-c:a", "aac", "-b:a", "128k", str(out)], capture_output=True, text=True)
    if done.returncode != 0:
        return "Couldn't convert that file: %s" % done.stderr[-120:]
    meta = load(MUSIC / "music.json", {})
    meta[out.name] = {"title": title, "credit": credit, "license": lic or "not stated", "source": url, "duration": round(seconds),
                      "added": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    save(MUSIC / "music.json", meta)
    return "Added %r (%d s). %s" % (title, seconds, "Its credit line will go in the caption of Reels that use it." if credit else "No credit line needed.")


def remove_music(name):
    meta = load(MUSIC / "music.json", {})
    path = MUSIC / Path(name).name
    if path.name not in meta and not path.exists():
        return "No such song."
    path.unlink(missing_ok=True)
    meta.pop(path.name, None)
    save(MUSIC / "music.json", meta)
    left = len(meta)
    return "Removed %s. %d song%s left%s." % (path.name, left, "" if left == 1 else "s", "; Reels will be silent until you add one" if not left else "")


def run(action, target, text):
    config = load(CONFIG, {})
    posted = load(POSTED, {})
    now = datetime.now(timezone.utc).isoformat()

    if action in ("pause", "resume"):
        config["paused"] = action == "pause"
        save(CONFIG, config)
        return "Publishing %s." % ("paused" if action == "pause" else "resumed")

    if action in ("posts_per_day", "reels_per_day"):
        n = int(target)
        if n not in SLOTS:
            return "Pick a number from 0 to 5."
        if action == "posts_per_day":
            config.update(posts_per_day=n, active_slots=SLOTS[n])
        else:
            config.update(reels_per_day=n, reel_active_slots=REEL_SLOTS[n])
        if config.get("posts_per_day", 0) + config.get("reels_per_day", 0) == 0:
            return "That would leave nothing to post. Keep at least one post or Reel a day."
        config["stories_per_day"] = max(config.get("posts_per_day", 0), config.get("reels_per_day", 0))
        config["max_posts_per_day"] = config.get("posts_per_day", 0) + config.get("reels_per_day", 0) + 1
        save(CONFIG, config)
        return "Now %d carousel post%s and %d Reel%s a day, from %d stories (takes effect from the next research run)." % (
            config["posts_per_day"], "" if config["posts_per_day"] == 1 else "s", config["reels_per_day"], "" if config["reels_per_day"] == 1 else "s", config["stories_per_day"])

    if action == "spares_per_day":
        n = int(target)
        if not 0 <= n <= 3:
            return "Spares per day must be 0 to 3."
        config["spares_per_day"] = n
        save(CONFIG, config)
        return "Spare posts per day set to %d (takes effect from the next research run)." % n

    if action == "refresh_dashboard":
        return "Dashboard rebuilt."
    if action == "add_music":
        return add_music(target, text)
    if action == "remove_music":
        return remove_music(target) if target else "No song was given."

    if action not in ("remove", "restore", "post_now", "reschedule", "replace", "edit_caption", "edit_slide", "delete_instagram", "post_reel"):
        return "Unknown action %r." % action
    if not target:
        return "No post was given."

    if action == "edit_slide":
        post_id, _, number = target.partition("#")
        try:
            index = int(number) - 1
        except ValueError:
            return "No slide number was given."

        def change(post):
            if not 0 <= index < len(post["slides"]):
                return "That slide doesn't exist."
            key = "headline" if post["slides"][index].get("type") == "cover" else "text"
            post["slides"][index][key] = text.strip()
        return edit_post(post_id, change, config, posted, slides_changed=True)

    if action == "edit_caption":
        def change(post):
            post["caption"] = text.strip()
        return edit_post(target, change, config, posted)

    if action == "replace":
        return replace(target, config, posted, now, text.strip() or None)

    if action == "post_reel":
        import publish_reel
        return publish_reel.post_reel(target)

    record = posted.get(target, {})
    if action == "remove":
        if record.get("status") == "posted":
            return "That post is already live; use Delete from Instagram instead."
        posted[target] = dict(record, status="removed", attempts=MAX_ATTEMPTS, removed_at=now)
        save(POSTED, posted)
        return "Removed %s; it will not be published." % target

    if action == "restore":
        if record.get("status") != "removed":
            return "%s was not removed." % target
        posted.pop(target)
        save(POSTED, posted)
        return "Restored %s; it publishes at its time (or use Post now)." % target

    if action == "post_now":
        if record.get("status") == "posted":
            return "%s is already live." % target
        record.pop("status", None)
        posted[target] = dict(record, attempts=0, post_now=True, post_now_requested_at=now)
        posted[target].pop("post_at", None)
        save(POSTED, posted)
        return "%s will be published at the next check (within a few minutes, unless a post went out in the last %d minutes)." % (
            target, config.get("min_minutes_between_posts", 45))

    if action == "reschedule":
        if record.get("status") in ("posted", "removed", "deleted"):
            return "%s is %s, so it can't be rescheduled." % (target, record["status"])
        if not text.strip():
            posted[target] = {k: v for k, v in record.items() if k not in ("post_at", "post_now")}
            save(POSTED, posted)
            return "%s goes back to its normal time slot." % target
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when > datetime.now(timezone.utc) + timedelta(days=7):
            return "Pick a time within the next 7 days."
        record.pop("post_now", None)
        posted[target] = dict(record, attempts=0, post_at=when.astimezone(timezone.utc).isoformat())
        posted[target].pop("status", None)
        save(POSTED, posted)
        return "%s will be published at %s UTC (or the first check after that)." % (target, when.astimezone(timezone.utc).strftime("%b %d %H:%M"))

    if action == "delete_instagram":
        media_id = find_media_id(target, posted)
        if not media_id:
            return "Couldn't find the Instagram post for %s." % target
        ok, error = delete_from_instagram(media_id, config)
        if not ok:
            return "Delete failed: %s. You can delete it in the Instagram app (... > Delete)." % error
        posted[target] = dict(record, status="deleted", deleted_at=now, attempts=MAX_ATTEMPTS)
        save(POSTED, posted)
        return "Deleted %s from Instagram." % target


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    target = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    text = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("TEXT", "")
    try:
        result = run(action, target, text)
    except Exception as exc:
        result = "Error: %s" % str(exc)[:200]
    print(result)
    log = load(LOG, [])
    log.insert(0, {"at": datetime.now(timezone.utc).isoformat(), "action": action, "target": target, "result": result})
    save(LOG, log[:50])


if __name__ == "__main__":
    main()
