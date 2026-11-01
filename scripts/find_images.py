"""Find free, high-resolution pictures on Wikimedia Commons without getting throttled.

Usage: python3 scripts/find_images.py "Shanidar Cave" "Neanderthal skeleton" [--min-width 2000] [--limit 6]

For each query it prints candidate pictures: a direct image URL (a standard-size thumbnail, which loads reliably), the pixel
size, the license and the credit line to use. Only free licenses are listed (public domain, CC0, CC BY, CC BY-SA).
It sends one request at a time with a pause between them, identifies itself properly, and obeys Wikimedia's Retry-After
when it is throttled, which is what the daily run kept failing at when it made its own search loops.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "UncleFactsBot/1.0 (+https://github.com/amirpz04/story-autopilot; image search)"
API = "https://commons.wikimedia.org/w/api.php"
GAP = 2.5                      # seconds between requests
FREE = ("public domain", "cc0", "cc by", "cc-by", "pd", "no restrictions", "usgov", "nasa")
_last = [0.0]


def get(url):
    for attempt in range(1, 6):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                pause = int(exc.headers.get("Retry-After") or 10 * attempt)
                print("  (throttled by Wikimedia, waiting %d s)" % pause, file=sys.stderr)
                time.sleep(min(pause, 60) + 1)
                continue
            raise
        except Exception:
            time.sleep(4 * attempt)
    return {}


def search(query, min_width, limit):
    params = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": query + " filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 2400,
        "iiextmetadatafilter": "Artist|LicenseShortName", "format": "json"})
    pages = get(API + "?" + params).get("query", {}).get("pages", {})
    found = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if info["width"] < min_width or not any(k in lic.lower() for k in FREE):
            continue
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()[:50] or "Unknown"
        url = info.get("thumburl") or info["url"]
        found.append({"title": page["title"][5:70], "url": url.split("?")[0], "size": "%dx%d" % (info["width"], info["height"]),
                      "license": lic, "credit": "Photo: %s / Wikimedia Commons, %s" % (artist, lic)})
        if len(found) >= limit:
            break
    return found


def main():
    args = sys.argv[1:]
    min_width, limit = 2000, 6
    if "--min-width" in args:
        i = args.index("--min-width"); min_width = int(args[i + 1]); del args[i:i + 2]
    if "--limit" in args:
        i = args.index("--limit"); limit = int(args[i + 1]); del args[i:i + 2]
    for q in args:
        print("### %s" % q)
        results = search(q, min_width, limit)
        for r in results:
            print("  %s | %s | %s\n    url: %s\n    credit: %s" % (r["title"], r["size"], r["license"], r["url"], r["credit"]))
        if not results:
            print("  (nothing free and large enough; try a different or broader query)")


if __name__ == "__main__":
    main()
