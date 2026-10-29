"""Render post.json files into 1080x1350 JPEG slides.

Usage:
    python scripts/render.py queue/2026-10-30          # all posts of a day -> preview/
    python scripts/render.py queue/2026-10-30/01       # one post
"""
import base64
import html
import json
import mimetypes
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "slide.html").read_text()
FONT_FILE = ROOT / "templates" / "fonts" / "Inter.ttf"
USER_AGENT = "StoryAccountBot/1.0 (Instagram story renderer)"
WIDTH, HEIGHT = 1080, 1350
FONT_DATA = "data:font/ttf;base64," + base64.b64encode(FONT_FILE.read_bytes()).decode()


def load_config():
    return json.loads((ROOT / "config.json").read_text())


def fetch_image(url):
    """Download an image and return it as a data URI, or None if it fails."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            mime = resp.headers.get_content_type()
        if not mime.startswith("image/"):
            mime = mimetypes.guess_type(url)[0] or "image/jpeg"
        return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())
    except Exception as exc:
        print("  ! image failed (%s): %s" % (exc, url))
        return None


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": USER_AGENT}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def search_pexels(query, orientation):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    params = urllib.parse.urlencode({"query": query, "orientation": orientation, "size": "large", "per_page": 1})
    photos = get_json("https://api.pexels.com/v1/search?" + params, {"Authorization": key}).get("photos")
    if not photos:
        return None
    photo = photos[0]
    return photo["src"]["original"] + "?auto=compress&cs=tinysrgb&w=1600", "Stock photo: %s / Pexels" % photo["photographer"]


def resolve_image(image, slide_type):
    """Return (url, credit) for a slide image: a direct url, or a Pexels stock photo search.

    Without a PEXELS_API_KEY (or with no match) the slide uses the text-only design.
    """
    if image.get("url"):
        return image["url"], image.get("credit", "")
    query = image.get("search")
    if not query:
        return None, ""
    orientation = "landscape" if slide_type == "text" else "portrait"
    try:
        found = search_pexels(query, orientation)
    except Exception as exc:
        print("  ! stock search failed (%s): %s" % (exc, query))
        found = None
    if not found:
        print("  ! no stock photo for %r, using text design" % query)
    return found or (None, "")


def slide_html(slide, index, total, config):
    brand = config["brand"]
    kind = slide["type"]
    url, credit = resolve_image(slide.get("image") or {}, kind)
    src = fetch_image(url) if url else None
    esc = lambda s: html.escape(s or "")

    if kind == "cover":
        body = (
            '<div class="kicker">%s</div><h1 class="fit">%s</h1>'
            % (esc(slide.get("kicker")), esc(slide["headline"]))
        )
    elif kind == "end":
        body = (
            '<p class="question fit">%s</p>'
            '<div class="follow">Follow <b>%s</b> for more stories like this</div>'
            % (esc(slide["text"]), esc(config["handle"]))
        )
    else:
        body = '<p class="fit">%s</p>' % esc(slide["text"])

    classes = [kind, "with-image" if src else "no-image"]
    return (
        TEMPLATE.replace("{{classes}}", " ".join(classes))
        .replace("{{bg}}", brand["background"])
        .replace("{{fg}}", brand["text"])
        .replace("{{accent}}", brand["accent"])
        .replace("{{font}}", brand["font"])
        .replace("{{fontdata}}", FONT_DATA)
        .replace("{{image}}", src or "")
        .replace("{{credit}}", esc(credit if src else ""))
        .replace("{{handle}}", esc(config["handle"]))
        .replace("{{counter}}", "%d/%d" % (index, total))
        .replace("{{body}}", body)
    )


def render_post(post_dir, out_dir, config=None):
    """Render one post folder; returns the list of JPEG paths in slide order."""
    from playwright.sync_api import sync_playwright

    config = config or load_config()
    post = json.loads((Path(post_dir) / "post.json").read_text())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        slides = post["slides"]
        for i, slide in enumerate(slides, 1):
            page.set_content(slide_html(slide, i, len(slides), config), wait_until="load")
            page.evaluate("document.fonts.ready.then(prepare)")
            path = out_dir / ("%s-%02d.jpg" % (post["id"], i))
            page.screenshot(path=str(path), type="jpeg", quality=95)
            paths.append(path)
        browser.close()
    return paths


def main():
    target = Path(sys.argv[1])
    posts = [target] if (target / "post.json").exists() else sorted(
        d for d in target.iterdir() if (d / "post.json").exists()
    )
    config = load_config()
    for post_dir in posts:
        print("Rendering", post_dir)
        for path in render_post(post_dir, ROOT / "preview", config):
            print("  ", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
