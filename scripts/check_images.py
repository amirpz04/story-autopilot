"""Download every picture used by a day's posts, report its real size, and save copies to look at.

For the daily Claude run: after choosing pictures, run this, then open each saved copy
(Read tool) and check that it matches its slide, is sharp, and isn't repeated.

Usage: python3 scripts/check_images.py queue/2026-10-31
Copies are saved to /tmp/imgcheck/<post-id>-slide<N>.<ext>. Needs no extra packages.
"""
import hashlib
import json
import struct
import sys
import urllib.request
from pathlib import Path

USER_AGENT = "StoryAccountBot/1.0 (image check)"
OUT = Path("/tmp/imgcheck")
MAX_BYTES = 60_000_000
BOXES = {"full": (1080, 1350), "cover": (1080, 1350), "split": (1080, 640)}  # the space a picture fills


def size_of(data):
    """(width, height) of a PNG, JPEG or WebP image, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def main():
    day = Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    problems = 0
    for path in sorted(day.glob("*/post.json")):
        post = json.loads(path.read_text())
        print("\n%s: %s" % (post["id"], post["title"]))
        seen = {}
        for n, slide in enumerate(post["slides"], 1):
            image = slide.get("image") or {}
            url = image.get("url")
            if not url:
                print("  slide %d: no picture%s" % (n, " (stock 'search' is not used any more; give a url)" if image.get("search") else ""))
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read(MAX_BYTES)
            except Exception as exc:
                print("  slide %d: CANNOT DOWNLOAD (%s): %s" % (n, exc, url))
                problems += 1
                continue
            dims = size_of(data)
            ext = "png" if data[:4] == b"\x89PNG" else "webp" if data[:4] == b"RIFF" else "jpg"
            copy = OUT / ("%s-slide%d.%s" % (post["id"], n, ext))
            copy.write_bytes(data)
            if not dims:
                print("  slide %d: NOT A READABLE IMAGE: %s" % (n, url))
                problems += 1
                continue
            kind = "cover" if slide["type"] == "cover" else ("full" if slide.get("layout") == "full" else "split")
            bw, bh = BOXES[kind]
            enlarge = max(bw / dims[0], bh / dims[1])
            verdict = "ok" if enlarge <= 1.25 else "TOO SMALL for a %s slide (would be dropped, replace it)" % kind
            digest = hashlib.md5(data).hexdigest()
            if digest in seen:
                verdict += "; DUPLICATE of slide %d" % seen[digest]
            seen.setdefault(digest, n)
            if verdict != "ok":
                problems += 1
            print("  slide %d: %dx%d %s -> %s | %s" % (n, dims[0], dims[1], kind, verdict, copy))
    print("\n%d problem(s) found." % problems)
    print("Now open each saved copy with the Read tool and check it matches its slide and is sharp.")


if __name__ == "__main__":
    main()
