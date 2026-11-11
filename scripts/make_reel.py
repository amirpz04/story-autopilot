"""Turn a queued post into an animated vertical video (a Reel): the same photos and text as the carousel.

Usage: python scripts/make_reel.py queue/2026-10-31/01 [out.mp4] [music.ogg | auto]

Draws every frame in the browser (smooth camera moves on photos, word-by-word text, transitions),
then encodes with ffmpeg. Needs Playwright with Chromium and ffmpeg; no other services, no cost.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_images import size_of  # noqa: E402

FPS = 30
USER_AGENT = "UncleFactsBot/1.0 (+https://github.com/amirpz04/story-autopilot; reel renderer)"
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


SECONDS_PER_WORD = 0.35   # about 170 words a minute, versus about 280 before: slower for readers whose first language is not English
BASE_SECONDS = 1.5        # fade-in and a moment to look at the picture before reading starts
MAX_REEL_SECONDS = 88     # Instagram Reels limit is 90 s; slow everything down only as far as this allows


def scene_duration(slide, pace=1.0):
    """How long a slide stays on screen, from the amount of text on it (every slide, automatically)."""
    words = len((slide.get("headline") or slide.get("text") or "").split())
    floor = 4.5 if slide["type"] == "cover" else 4.0
    return min(16.0, max(floor, BASE_SECONDS + words * SECONDS_PER_WORD)) * pace


def build_scenes(post, work):
    scenes, t = [], 0.0
    est = sum(scene_duration(s) for s in post["slides"])
    pace = min(1.0, (MAX_REEL_SECONDS - 6) / est) if est else 1.0   # only very long posts get squeezed, never below the limit
    for n, slide in enumerate(post["slides"]):
        image = slide.get("image") or {}
        photo, ar = None, None
        if image.get("url"):
            data, last = None, None
            for attempt in range(1, 5):                        # retry throttled downloads (HTTP 429/503) with a growing pause
                try:
                    req = urllib.request.Request(image["url"], headers={"User-Agent": USER_AGENT})
                    data = urllib.request.urlopen(req, timeout=90).read()
                    break
                except Exception as exc:
                    last = exc
                    time.sleep(6 * attempt)
            if data is None:
                raise RuntimeError("picture could not be downloaded (%s): %s" % (last, image["url"]))   # never make a Reel with a gap
            dims = size_of(data)
            if dims and dims[0] >= 900:
                ext = "png" if data[:4] == b"\x89PNG" else "webp" if data[:4] == b"RIFF" else "jpg"
                path = work / f"photo{n}.{ext}"
                path.write_bytes(data)
                photo, ar = path.as_uri(), dims[0] / dims[1]
        dur = scene_duration(slide, pace) + (min(2.0, 0.55 * len(image.get("marks") or [])) if photo else 0)   # time to see the marks
        frames = None
        if image.get("video"):                                  # moving footage behind the text instead of a still picture
            try:
                vsrc, vpath = image["video"], work / f"video{n}.mp4"
                if vsrc.startswith("file://"):
                    shutil.copy(vsrc[7:], vpath)
                else:
                    for attempt in range(1, 5):
                        try:
                            req = urllib.request.Request(vsrc, headers={"User-Agent": USER_AGENT})
                            with urllib.request.urlopen(req, timeout=180) as r, open(vpath, "wb") as f:
                                shutil.copyfileobj(r, f)
                            break
                        except Exception as exc:
                            time.sleep(6 * attempt)
                    else:
                        raise RuntimeError("video could not be downloaded: %s" % vsrc)
                fdir = work / f"vid{n}"
                fdir.mkdir()
                seconds = dur + 0.5
                fx = float(image.get("focus_x", 0.5))               # which part of a wide video stays in the 9:16 crop
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(image.get("start", 0)), "-t", "%.2f" % seconds, "-i", str(vpath),
                                "-vf", "fps=%d,scale=-2:1920,crop=1080:1920:(iw-1080)*%.3f:0" % (FPS, fx), "-q:v", "4", str(fdir / "f%04d.jpg")], check=True)
                frames = [q.as_uri() for q in sorted(fdir.glob("f*.jpg"))]
                if not frames:
                    raise RuntimeError("no frames could be cut from the video: %s" % vsrc)
                photo, ar = frames[0], 1080 / 1920
            except Exception as exc:                            # a broken clip never stops a Reel: the still picture is used
                print("Video not used on slide %d (%s); using the picture instead." % (n + 1, str(exc)[:120]))
                frames = None
                if not photo:
                    raise
        scenes.append({
            "type": slide["type"], "kicker": (slide.get("kicker") or "").upper() if slide["type"] == "cover" else "",
            "text": slide.get("headline") or slide.get("text") or "", "photo": photo, "ar": ar,
            "credit": image.get("credit", "") if photo else "", "marks": (image.get("marks") or []) if photo else [],
            "focus": image.get("focus") if photo else None, "start": round(t, 3), "dur": round(dur, 3), "dir": 1 if n % 2 == 0 else -1,
            **({"frames": frames} if frames else {}),
        })
        t += dur
    return scenes


def _render_frames(job):
    """Draw frames [start, stop) in its own browser (run in a separate process so several can work at once)."""
    page_file, frames_dir, start, stop = job
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(page_file)
        page.evaluate("document.fonts.ready")
        page.evaluate("Promise.all([...document.images].map(i => i.decode().catch(() => null)))")
        page.evaluate("fitAll()")
        for f in range(start, stop):
            page.evaluate("async t => { render(t); await Promise.all((window.__pend || []).splice(0)); }", f / FPS)   # wait for video frames to load
            page.screenshot(path=str(Path(frames_dir) / f"f_{f:05d}.jpg"), type="jpeg", quality=93)
        browser.close()
    return stop - start


def make_reel(post_dir, out_path, config=None, music=None):
    from playwright.sync_api import sync_playwright

    config = config or load_config()
    post = json.loads((Path(post_dir) / "post.json").read_text())
    work = Path(tempfile.mkdtemp(prefix="reel-"))
    frames = work / "frames"
    frames.mkdir()
    scenes = build_scenes(post, work)
    html = (ROOT / "templates" / "reel.html").read_text()
    html = html.replace("/*MARKSJS*/", (ROOT / "templates" / "marks.js").read_text()).replace("/*FONT*/", FONT.as_uri()).replace("/*HANDLE*/", config["handle"])
    html = html.replace("/*SCENES*/[]/*END*/", json.dumps(scenes))
    page_file = work / "reel.html"
    page_file.write_text(html)

    total = scenes[-1]["start"] + scenes[-1]["dur"] + 0.3
    count = int(total * FPS)
    print("%d scenes, %.1f s, %d frames" % (len(scenes), total, count))
    workers = max(1, min(4, os.cpu_count() or 1))          # frames are drawn by several browsers at once
    per = -(-count // workers)
    jobs = [(page_file.as_uri(), str(frames), k * per, min(count, (k + 1) * per)) for k in range(workers) if k * per < count]
    if len(jobs) == 1:
        _render_frames(jobs[0])
    else:
        import multiprocessing
        with multiprocessing.get_context("spawn").Pool(len(jobs)) as pool:
            pool.map(_render_frames, jobs)

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
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(FPS),
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
