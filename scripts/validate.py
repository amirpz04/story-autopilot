"""Check queued posts for problems before they can be published.

Usage: python scripts/validate.py queue/2026-10-30
Exits with status 1 and prints every problem if anything is wrong.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MAX_SLIDE_WORDS = 50
MAX_HEADLINE_WORDS = 16
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 5


def check_post(path, config):
    errors = []
    try:
        post = json.loads(path.read_text())
    except Exception as exc:
        return ["invalid JSON: %s" % exc]

    for key in ("id", "date", "slot", "title", "sources", "slides", "caption"):
        if key not in post:
            errors.append("missing '%s'" % key)
    if errors:
        return errors

    if not 1 <= post["slot"] <= len(config["post_times"]):
        errors.append("slot %s has no publishing time in config.json" % post["slot"])
    if not post["sources"] or not all(s.get("url", "").startswith("http") for s in post["sources"]):
        errors.append("every source needs a url")

    slides = post["slides"]
    if not 2 <= len(slides) <= 10:
        errors.append("needs 2-10 slides, has %d" % len(slides))
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
        if image:
            url = image.get("url", "")
            if not url.startswith("https://"):
                errors.append("slide %d: image url must start with https://" % i)
            if not url.lower().split("?")[0].endswith(IMAGE_EXTS):
                errors.append("slide %d: image url must be a direct image file" % i)
            if not image.get("credit"):
                errors.append("slide %d: image needs a credit" % i)

    caption = post["caption"] + "\n\n" + " ".join(post.get("hashtags", []))
    if len(caption) > MAX_CAPTION_CHARS:
        errors.append("caption + hashtags is %d chars, max %d" % (len(caption), MAX_CAPTION_CHARS))
    if len(post.get("hashtags", [])) > MAX_HASHTAGS:
        errors.append("max %d hashtags" % MAX_HASHTAGS)
    return errors


def main():
    day_dir = Path(sys.argv[1])
    config = json.loads((ROOT / "config.json").read_text())
    posts = sorted(day_dir.glob("*/post.json"))
    if not posts:
        print("No posts found in", day_dir)
        sys.exit(1)

    failed = False
    slots = {}
    for path in posts:
        errors = check_post(path, config)
        try:
            slot = json.loads(path.read_text()).get("slot")
            if slot in slots:
                errors.append("slot %s is also used by %s" % (slot, slots[slot]))
            slots[slot] = path.parent.name
        except Exception:
            pass
        status = "OK" if not errors else "FAIL"
        print("%s  %s" % (status, path.relative_to(ROOT) if path.is_absolute() else path))
        for err in errors:
            print("      -", err)
        failed = failed or bool(errors)
    print("%d posts checked" % len(posts))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
