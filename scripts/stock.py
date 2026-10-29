"""Find Unsplash stock photos for slides that ask for one, within a strict hourly budget.

A slide image like {"search": "scientist holding test tubes"} is resolved once into
{"url": ..., "credit": ...} and saved back into post.json, so rendering and
publishing never call Unsplash again. Each photo costs 2 API requests (search +
the download notification Unsplash's guidelines require). Requests are logged in
state/unsplash_requests.json and never exceed `unsplash_max_requests_per_hour`
(config.json) in any rolling hour. Slides that don't get a photo in time use the
text-only design.

Usage: python scripts/stock.py queue/2026-10-30
Environment: UNSPLASH_ACCESS_KEY
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "state" / "unsplash_requests.json"
API = "https://api.unsplash.com"
APP_NAME = "story_account"  # used in the referral links Unsplash asks for
COST_PER_PHOTO = 2


class Budget:
    """Rolling one-hour request counter, persisted between runs."""

    def __init__(self, max_per_hour):
        self.max = max_per_hour
        stamps = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []
        self.stamps = [t for t in stamps if t > time.time() - 3600]

    def left(self):
        return self.max - len(self.stamps)

    def spend(self):
        if self.left() <= 0:
            raise RuntimeError("Unsplash hourly budget exhausted")
        self.stamps.append(time.time())
        LOG_FILE.write_text(json.dumps(self.stamps) + "\n")


def api_get(path, key, budget, **params):
    budget.spend()
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Client-ID " + key, "Accept-Version": "v1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def find_photo(query, slide_type, key, budget):
    orientation = "landscape" if slide_type == "text" else "portrait"
    results = api_get("/search/photos", key, budget, query=query[:100], orientation=orientation,
                      per_page=1, content_filter="high").get("results")
    if not results:
        return None
    photo = results[0]
    # Unsplash requires notifying this endpoint when a photo is used.
    dl = urllib.parse.urlparse(photo["links"]["download_location"])
    api_get(dl.path, key, budget, **dict(urllib.parse.parse_qsl(dl.query)))
    ref = "?utm_source=%s&utm_medium=referral" % APP_NAME
    return {
        "url": photo["urls"]["raw"] + "&w=1600&fm=jpg&q=85",
        "credit": "Photo by %s on Unsplash" % photo["user"]["name"],
        "search": query,
        "source": photo["links"]["html"] + ref,
        "photographer_url": photo["user"]["links"]["html"] + ref,
    }


def main():
    day_dir = Path(sys.argv[1])
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        print("No UNSPLASH_ACCESS_KEY set; stock photo slides will use the text design.")
        return
    config = json.loads((ROOT / "config.json").read_text())
    budget = Budget(config.get("unsplash_max_requests_per_hour", 30))

    # Earliest posts first, so the next posts to go out get their photos first.
    for path in sorted(day_dir.glob("*/post.json"), key=lambda p: json.loads(p.read_text())["slot"]):
        post = json.loads(path.read_text())
        changed = False
        for slide in post["slides"]:
            image = slide.get("image") or {}
            if "url" in image or not image.get("search") or image.get("not_found"):
                continue
            if budget.left() < COST_PER_PHOTO:
                print("Hourly budget reached (%d used); the rest will be fetched next run." % len(budget.stamps))
                break
            try:
                found = find_photo(image["search"], slide["type"], key, budget)
            except Exception as exc:
                print("  ! Unsplash error for %r: %s" % (image["search"], exc))
                continue
            slide["image"] = found or dict(image, not_found=True)
            changed = True
            print("  %s: %r -> %s" % (post["id"], image["search"], found["credit"] if found else "no result"))
        if changed:
            path.write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")
        if budget.left() < COST_PER_PHOTO:
            break
    print("Unsplash requests in the last hour: %d/%d" % (len(budget.stamps), budget.max))


if __name__ == "__main__":
    main()
