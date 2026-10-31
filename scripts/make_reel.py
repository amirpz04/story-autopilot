"""Turn a queued post into an animated vertical video (a Reel): the same photos and text as the carousel.

Usage: python scripts/make_reel.py queue/2026-10-31/01 [out.mp4] [music.ogg | auto]

Draws every frame in the browser (smooth camera moves on photos, word-by-word text, transitions),
then encodes with ffmpeg. Needs Playwright with Chromium and ffmpeg; no other services, no cost.
"""
import json
import random
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_images import size_of  # noqa: E402

FPS = 30
USER_AGENT = "StoryAccountBot/1.0 (reel renderer)"
FONT = ROOT / "templates" / "fonts" / "Inter.ttf"


MUSIC_DIR = ROOT / "assets" / "music"
MUSIC_LOG = ROOT / "state" / "music_log.json"


def pick_music(log_path=MUSIC_LOG):
    """Next track: never one of the most recently used, so the same song doesn't repeat.

    Returns (path or None, credit line to put in the caption, or "").
    """
    tracks = sorted(t for t in MUSIC_DIR.iterdir() if t.suffix in (".m4a", ".mp3", ".ogg", ".wav"))
    if not tracks:
        return None, ""
    try:
        used = json.loads(Path(log_path).read_text())
    except Exception:
        used = []
    recent = [Path(u).stem for u in used[-(len(tracks) - 1):]] if len(tracks) > 1 else []
    choice = random.choice([t for t in tracks if t.stem not in recent] or tracks)
    Path(log_path).write_text(json.dumps((used + [choice.name])[-30:]) + "\n")
    try:
        credit = json.loads((MUSIC_DIR / "music.json").read_text()).get(choice.name, {}).get("credit", "")
    except Exception:
        credit = ""
    return choice, credit


def load_config():
    return json.loads((ROOT / "config.json").read_text())


def scene_duration(slide):
    words = len((slide.get("headline") or slide.get("text") or "").split())
    if slide["type"] == "cover":
        return min(5.0, max(3.4, 2.1 + words * 0.26))
    if slide["type"] == "end":
        return 3.6
    return min(6.4, max(2.9, 1.5 + words * 0.31))


def build_scenes(post, work):
    scenes, t = [], 0.0
    for n, slide in enumerate(post["slides"]):
        image = slide.get("image") or {}
        photo, ar = None, None
        if image.get("url"):
            try:
                req = urllib.request.Request(image["url"], headers={"User-Agent": USER_AGENT})
                data = urllib.request.urlopen(req, timeout=90).read()
                dims = size_of(data)
                if dims and dims[0] >= 900:
                    ext = "png" if data[:4] == b"\x89PNG" else "webp" if data[:4] == b"RIFF" else "jpg"
                    path = work / f"photo{n}.{ext}"
                    path.write_bytes(data)
                    photo, ar = path.as_uri(), dims[0] / dims[1]
            except Exception as exc:
                print("  ! picture skipped (%s): %s" % (exc, image["url"]))
        dur = scene_duration(slide)
        scenes.append({
            "type": slide["type"], "kicker": (slide.get("kicker") or "").upper() if slide["type"] == "cover" else "",
            "text": slide.get("headline") or slide.get("text") or "", "photo": photo, "ar": ar,
            "credit": image.get("credit", "") if photo else "", "start": round(t, 3), "dur": round(dur, 3), "dir": 1 if n % 2 == 0 else -1,
        })
        t += dur
    return scenes


def make_reel(post_dir, out_path, config=None, music=None):
    from playwright.sync_api import sync_playwright

    config = config or load_config()
    post = json.loads((Path(post_dir) / "post.json").read_text())
    work = Path(tempfile.mkdtemp(prefix="reel-"))
    frames = work / "frames"
    frames.mkdir()
    scenes = build_scenes(post, work)
    html = (ROOT / "templates" / "reel.html").read_text()
    html = html.replace("/*FONT*/", FONT.as_uri()).replace("/*HANDLE*/", config["handle"])
    html = html.replace("/*SCENES*/[]/*END*/", json.dumps(scenes))
    page_file = work / "reel.html"
    page_file.write_text(html)

    total = scenes[-1]["start"] + scenes[-1]["dur"] + 0.3
    count = int(total * FPS)
    print("%d scenes, %.1f s, %d frames" % (len(scenes), total, count))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(page_file.as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate("Promise.all([...document.images].map(i => i.decode().catch(() => null)))")
        page.evaluate("fitAll()")
        for f in range(count):
            page.evaluate("t => render(t)", f / FPS)
            page.screenshot(path=str(frames / f"f_{f:05d}.jpg"), type="jpeg", quality=93)
        browser.close()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if music:   # free music (see assets/music/README.md), looped to length, loudness-matched, faded in and out
        audio_in = ["-stream_loop", "-1", "-i", str(music)]
        audio_map = ["-filter_complex",
                     "[1:a]atrim=0:%.2f,asetpts=N/SR/TB,loudnorm=I=-17:TP=-2:LRA=7,afade=t=in:d=1.2,afade=t=out:st=%.2f:d=2.3[a]" % (total, total - 2.4),
                     "-map", "0:v", "-map", "[a]"]
    else:
        audio_in = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        audio_map = []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"), *audio_in,
                    "-t", "%.2f" % total, *audio_map,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    shutil.rmtree(work, ignore_errors=True)
    return out_path


if __name__ == "__main__":
    post_dir = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "preview" / "reel.mp4")
    music, credit = (sys.argv[3] if len(sys.argv) > 3 else None), ""
    if music == "auto":
        music, credit = pick_music()
        print("Music:", music.name if music else "none", "| credit line:", credit or "(none needed)")
    print("Wrote", make_reel(post_dir, out, music=music))
