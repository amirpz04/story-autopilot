"""Check queued posts for problems before they can be published.

Usage: python scripts/validate.py queue/2026-10-30
Exits with status 1 and prints every problem if anything is wrong.
"""
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MAX_SLIDE_WORDS = 40
MAX_HEADLINE_WORDS = 16
MIN_CAPTION_CHARS = 700
MAX_CAPTION_CHARS = 1500
MAX_HASHTAGS = 5


def norm_url(url):
    url = url.lower().split("#")[0].split("?")[0]
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


def norm_title(title):
    return re.sub(r"[^a-z0-9 ]", "", title.lower())


def known_stories(this_path):
    """Every story already used: state/history.jsonl plus all other queued posts."""
    stories = []
    history = ROOT / "state" / "history.jsonl"
    if history.exists():
        for line in history.read_text().splitlines():
            if line.strip():
                h = json.loads(line)
                stories.append({"id": h.get("id", h.get("title")), "title": h.get("title", ""),
                                "urls": h.get("urls") or [h.get("url", "")]})
    for other in (ROOT / "queue").glob("*/*/post.json"):
        if other.resolve() == this_path.resolve() or other.parent.parent.name in ("sample", "demo"):
            continue
        try:
            o = json.loads(other.read_text())
            stories.append({"id": o["id"], "title": o["title"], "urls": [x["url"] for x in o["sources"]]})
        except Exception:
            pass
    return stories


def check_duplicates(post, this_path):
    errors = []
    urls = {norm_url(s["url"]) for s in post["sources"]}
    for story in known_stories(this_path):
        if story["id"] == post["id"]:
            continue
        if urls & {norm_url(u) for u in story["urls"] if u}:
            errors.append("duplicate: same source as %s" % story["id"])
        elif SequenceMatcher(None, norm_title(post["title"]), norm_title(story["title"])).ratio() > 0.7:
            errors.append("possible duplicate of %s (very similar title): %r" % (story["id"], story["title"]))
    return errors


def final_problems(post):
    """Checks on the photos that really exist after the stock lookup (not just requested ones)."""
    problems, urls, run = [], [], 0
    for i, sl in enumerate(post["slides"], 1):
        url = (sl.get("image") or {}).get("url")
        if url:
            urls.append(url.split("?")[0])
            run = 0
        elif sl.get("type") == "text":
            run += 1
            if run == 2:
                problems.append("slides %d-%d have no picture, two plain slides in a row" % (i - 1, i))
    need = max(3, (len(post["slides"]) + 1) // 2)
    if len(urls) < need:
        problems.append("only %d slides have a picture (direct image url); at least %d are needed for %d slides" % (len(urls), need, len(post["slides"])))
    if len(set(urls)) < len(urls):
        problems.append("the same picture is used on more than one slide")
    return problems


def check_post(path, config):
    errors = []
    try:
        post = json.loads(path.read_text())
    except Exception as exc:
        return ["invalid JSON: %s" % exc]

    spare = bool(post.get("spare"))          # a spare has no time slot until it replaces a scheduled post
    for key in ("id", "date", "title", "sources", "slides", "caption"):
        if key not in post:
            errors.append("missing '%s'" % key)
    if errors:
        return errors

    if not spare:
        slot, reel_slot = post.get("slot"), post.get("reel_slot")
        if slot is None and reel_slot is None:
            errors.append("the post needs a carousel `slot`, a `reel_slot`, or both")
        if slot is not None:
            if not 1 <= slot <= len(config["post_times"]):
                errors.append("slot %s has no publishing time in config.json" % slot)
            if "active_slots" in config and slot not in config["active_slots"]:
                errors.append("slot %s is not one of the active slots %s in config.json" % (slot, config["active_slots"]))
        if reel_slot is not None:
            if not 1 <= reel_slot <= len(config.get("reel_times", [])):
                errors.append("reel_slot %s has no time in config.json reel_times" % reel_slot)
            if "reel_active_slots" in config and reel_slot not in config["reel_active_slots"]:
                errors.append("reel_slot %s is not one of the active Reel slots %s in config.json" % (reel_slot, config["reel_active_slots"]))
    if not post["sources"] or not all(s.get("url", "").startswith("http") for s in post["sources"]):
        errors.append("every source needs a url")

    slides = post["slides"]
    if not 5 <= len(slides) <= 10:
        errors.append("needs 5-10 slides, has %d" % len(slides))
    errors += final_problems(post)
    for i, sl in enumerate(slides, 1):
        if (sl.get("image") or {}).get("search") and not sl["image"].get("url"):
            errors.append("slide %d: stock 'search' pictures are not used any more; give a direct image url" % i)
        if sl.get("layout") not in (None, "split", "full"):
            errors.append("slide %d: layout must be 'split' or 'full'" % i)
    if slides and slides[0].get("type") != "cover":
        errors.append("first slide must be type 'cover'")
    if slides and slides[-1].get("type") != "end":
        errors.append("last slide must be type 'end'")

    for i, slide in enumerate(slides, 1):
        kind = slide.get("type")
        if kind not in ("cover", "text", "end"):
            errors.append("slide %d: unknown type %r" % (i, kind))
            continue
        field = "headline" if kind == "cover" else "text"
        words = len((slide.get(field) or "").split())
        if words == 0:
            errors.append("slide %d: '%s' is empty" % (i, field))
        limit = MAX_HEADLINE_WORDS if kind == "cover" else MAX_SLIDE_WORDS
        if words > limit:
            errors.append("slide %d: %d words, max %d" % (i, words, limit))
        image = slide.get("image")
        if image and "url" not in image:
            if not image.get("search", "").strip():
                errors.append("slide %d: image needs a 'url' or a stock 'search'" % i)
        elif image:
            url = image.get("url", "")
            if not url.startswith("https://"):
                errors.append("slide %d: image url must start with https://" % i)
            if not url.lower().split("?")[0].endswith(IMAGE_EXTS) and not url.startswith("https://images.unsplash.com/"):
                errors.append("slide %d: image url must be a direct image file" % i)
            if not image.get("credit"):
                errors.append("slide %d: image needs a credit" % i)

    in_caption = [t for t in post.get("hashtags", []) if t.lower() in post["caption"].lower()]
    if in_caption:
        errors.append("hashtags %s are written in the caption; keep them only in the hashtags field" % " ".join(in_caption))
    errors += check_duplicates(post, path)

    caption = post["caption"] + "\n\n" + " ".join(post.get("hashtags", []))
    if len(post["caption"]) < MIN_CAPTION_CHARS:
        errors.append("caption is %d chars; write a detailed one of at least %d" % (len(post["caption"]), MIN_CAPTION_CHARS))
    if len(caption) > MAX_CAPTION_CHARS:
        errors.append("caption + hashtags is %d chars, max %d" % (len(caption), MAX_CAPTION_CHARS))
    if len(post.get("hashtags", [])) > MAX_HASHTAGS:
        errors.append("max %d hashtags" % MAX_HASHTAGS)
    return errors


def main():
    day_dir = Path(sys.argv[1])
    config = json.loads((ROOT / "config.json").read_text())
    posts = sorted(p for p in day_dir.glob("*/post.json") if "-replaced" not in p.parent.name)
    if not posts:
        print("No posts found in", day_dir)
        sys.exit(1)

    failed = False
    slots = {}
    for path in posts:
        errors = check_post(path, config)
        try:
            slot = json.loads(path.read_text()).get("slot")
            if slot is not None and slot in slots:
                errors.append("slot %s is also used by %s" % (slot, slots[slot]))
            slots[slot] = path.parent.name
        except Exception:
            pass
        status = "OK" if not errors else "FAIL"
        try:
            shown = path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            shown = path
        print("%s  %s" % (status, shown))
        for err in errors:
            print("      -", err)
        failed = failed or bool(errors)
    print("%d posts checked" % len(posts))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
