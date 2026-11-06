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
FONT = ROOT / "templates" / "fonts" / "Bricolage.ttf"
FONT_DISPLAY = ROOT / "templates" / "fonts" / "Unbounded.ttf"
FONT_MONO = ROOT / "templates" / "fonts" / "JetBrainsMono.ttf"


MUSIC_DIR = ROOT / "assets" / "music"
MUSIC_LOG = ROOT / "state" / "music_log.json"


def _cached(url, name):
    """Remote tracks (free-to-use libraries we only link to) are fetched when a Reel is made."""
    import tempfile
    cache = Path(tempfile.gettempdir()) / "uf-music"
    cache.mkdir(exist_ok=True)
    path = cache / name
    if path.exists() and path.stat().st_size > 50000:
        return path
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
            return path
        except Exception as exc:
            last = exc
            time.sleep(3 * attempt)
    raise RuntimeError("song could not be downloaded (%s): %s" % (last, url))


def pick_music(mood=None, log_path=MUSIC_LOG):
    """A song that fits the story's mood (hype, playful, tense, mysterious, inspiring, chill), rotating so it doesn't repeat.

    With no mood any song is fine. With a mood nothing in the library fits, the Reel has no music (the voice alone
    beats a song that clashes); the daily run is told to add a fitting one (ROUTINE.md section 7).
    Returns (path or None, credit line to put in the caption, or "").
    """
    try:
        meta = json.loads((MUSIC_DIR / "music.json").read_text())
    except Exception:
        return None, ""
    cands = [n for n, m in meta.items() if (MUSIC_DIR / n).exists() or m.get("remote")]
    if mood:
        cands = [n for n in cands if mood in (meta[n].get("mood") or [])]
    if not cands:
        return None, ""
    try:
        used = json.loads(Path(log_path).read_text())
    except Exception:
        used = []
    recent = used[-(len(cands) - 1):] if len(cands) > 1 else []
    name = random.choice([n for n in cands if n not in recent] or cands)
    Path(log_path).write_text(json.dumps((used + [name])[-30:]) + "\n")
    m = meta[name]
    path = _cached(m["source"], name) if m.get("remote") else MUSIC_DIR / name
    return path, m.get("credit", "")


def load_config():
    return json.loads((ROOT / "config.json").read_text())


def scene_duration(slide):
    words = len((slide.get("headline") or slide.get("text") or "").split())
    if slide["type"] == "cover":
        return min(5.0, max(3.4, 2.1 + words * 0.26))
    if slide["type"] == "end":
        return 3.6
    return min(6.4, max(2.9, 1.5 + words * 0.31))


def build_scenes(post, work, handle="@unclefactss"):
    scenes, t = [], 0.0
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
        dur = scene_duration(slide) + (min(2.0, 0.55 * len(image.get("marks") or [])) if photo else 0)   # time to see the marks
        scenes.append({
            "type": slide["type"], "kicker": (slide.get("kicker") or "").upper() if slide["type"] == "cover" else "",
            "text": ((slide.get("headline") or slide.get("text") or "") + (" Follow %s for more" % handle if slide["type"] == "end" else "")),
            "photo": photo, "ar": ar,
            "credit": image.get("credit", "") if photo else "", "marks": (image.get("marks") or []) if photo else [],
            "focus": image.get("focus") if photo else None, "start": round(t, 3), "dur": round(dur, 3), "dir": 1 if n % 2 == 0 else -1,
        })
        scenes[-1]["words"] = word_times(scenes[-1]["text"], None, dur - 0.55, 0.2)     # replaced by the real timing when there is a voice
        t += dur
    return scenes


def word_times(text, bounds, length, lead):
    """When each word of the on-screen text is shown: [{"w", "t", "e"}] in seconds from the scene start.

    The spoken words (`bounds`: [start, end, word] from the voice) can differ from the written ones ("40%" is spoken
    "forty percent"), so both are laid on a 0-1 scale by letters and matched there. Without a voice, the words are
    spread evenly over `length`.
    """
    words = text.split()
    if not words:
        return []
    total, pos, starts, ends = sum(len(w) + 1 for w in words), 0, [], []
    for w in words:
        starts.append(pos / total)
        pos += len(w) + 1
        ends.append((pos - 1) / total)
    anchors = [(0.0, 0.05), (1.0, max(0.2, length - 0.05))]
    if bounds:
        tot, pos, anchors = sum(len(b[2]) + 1 for b in bounds), 0, []
        for t0, t1, word in bounds:
            anchors += [(pos / tot, t0), ((pos + len(word)) / tot, t1)]
            pos += len(word) + 1
        anchors = [(0.0, anchors[0][1])] + anchors + [(1.0, bounds[-1][1])]

    def at(f):
        for (f0, t0), (f1, t1) in zip(anchors, anchors[1:]):
            if f <= f1:
                return t0 if f1 <= f0 else t0 + (t1 - t0) * max(0.0, (f - f0)) / (f1 - f0)
        return anchors[-1][1]
    return [{"w": w, "t": round(lead + at(a), 3), "e": round(lead + at(b), 3)} for w, a, b in zip(words, starts, ends)]


def narration(slide, config):
    """What the narrator says on a slide: its own `say` line if the story has one, otherwise the slide's text."""
    if slide.get("say"):
        return slide["say"]
    text = slide.get("headline") or slide.get("text") or ""
    if slide["type"] == "end":
        text += " Follow %s for more." % config.get("account_name", "us")
    return text


def add_voice(post, scenes, work, config):
    """Read every slide aloud and stretch each scene to its line. Returns the voice clips [(path, start)] or [] (no voice)."""
    if not config.get("voiceover"):
        return []
    lines = [narration(sl, config) for sl in post["slides"]]
    (work / "lines.json").write_text(json.dumps(lines))
    python = os.environ.get("TTS_PYTHON") or sys.executable
    try:
        res = subprocess.run([python, str(ROOT / "scripts" / "voice.py"), str(work / "lines.json"), str(work / "voice"),
                              config.get("voice", "am_michael"), str(config.get("voice_speed", 1.05))],
                             capture_output=True, text=True, timeout=900, check=True)
        got = json.loads(res.stdout.strip().splitlines()[-1])
        lengths, bounds = got["lengths"], got["bounds"]
        print("Voice:", (res.stderr.strip().splitlines() or ["?"])[-1][:120])
    except Exception as exc:
        print("Voiceover failed, making the Reel without it:", str(getattr(exc, "stderr", "") or exc)[-400:])
        return []
    clips, t = [], 0.0
    for i, (sc, length) in enumerate(zip(scenes, lengths)):
        extra = min(2.0, 0.55 * len(sc.get("marks") or []))
        sc["dur"] = round(max(2.4, 0.25 + length + 0.35) + extra * 0.4, 3)        # the line, a breath after it, a moment for marks
        sc["start"] = round(t, 3)
        sc["words"] = word_times(sc["text"], bounds[i], length, 0.25)
        clips.append((work / "voice" / ("line_%02d.wav" % i), t + 0.25))
        t += sc["dur"]
    return clips


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
            page.evaluate("t => render(t)", f / FPS)
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
    scenes = build_scenes(post, work, config.get("handle", "@unclefactss"))
    voice = add_voice(post, scenes, work, config)
    html = (ROOT / "templates" / "reel.html").read_text()
    html = html.replace("/*MARKSJS*/", (ROOT / "templates" / "marks.js").read_text()).replace("/*FONT*/", FONT.as_uri()).replace("/*FONTMONO*/", FONT_MONO.as_uri()).replace("/*FONTDISPLAY*/", FONT_DISPLAY.as_uri()).replace("/*HANDLE*/", config["handle"])
    html = html.replace("/*SCENES*/[]/*END*/", json.dumps(scenes))
    page_file = work / "reel.html"
    page_file.write_text(html)

    total = scenes[-1]["start"] + scenes[-1]["dur"] + 0.3
    count = int(total * FPS)
    print("%d scenes, %.1f s, %d frames" % (len(scenes), total, count))
    t0 = time.time()
    workers = max(1, min(4, os.cpu_count() or 1))          # frames are drawn by several browsers at once
    per = -(-count // workers)
    jobs = [(page_file.as_uri(), str(frames), k * per, min(count, (k + 1) * per)) for k in range(workers) if k * per < count]
    if len(jobs) == 1:
        _render_frames(jobs[0])
    else:
        import multiprocessing
        with multiprocessing.get_context("spawn").Pool(len(jobs)) as pool:
            pool.map(_render_frames, jobs)

    print("Frames drawn in %.0f s (%d workers)" % (time.time() - t0, len(jobs)))
    t1 = time.time()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if music or voice:
        # free music (see assets/music/), looped to length and faded; when there is a voiceover the music sits quietly under it
        audio_in, parts, n = [], [], 1
        if music:
            audio_in += ["-stream_loop", "-1", "-i", str(music)]
            level = "volume=0.16" if voice else "loudnorm=I=-17:TP=-2:LRA=7"
            parts.append("[1:a]atrim=0:%.2f,asetpts=N/SR/TB,aformat=sample_rates=44100:channel_layouts=stereo,%s,afade=t=in:d=1.2,afade=t=out:st=%.2f:d=2.3[m]" % (total, level, total - 2.4))
            n = 2
        for k, (clip, start) in enumerate(voice):
            audio_in += ["-i", str(clip)]
            ms = int(start * 1000)
            parts.append("[%d:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay=%d|%d[v%d]" % (n + k, ms, ms, k))
        if voice:
            parts.append("".join("[v%d]" % k for k in range(len(voice))) + "amix=inputs=%d:normalize=0:duration=longest[vo]" % len(voice))
            parts.append(("[m][vo]amix=inputs=2:normalize=0:duration=first," if music else "[vo]") + "loudnorm=I=-15:TP=-1.5:LRA=9,apad[a]")
        else:
            parts.append("[m]anull[a]")
        audio_map = ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]"]
    else:
        audio_in = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        audio_map = []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"), *audio_in,
                    "-t", "%.2f" % total, *audio_map,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    print("Encoded in %.0f s" % (time.time() - t1))
    shutil.rmtree(work, ignore_errors=True)
    return out_path


if __name__ == "__main__":
    post_dir = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "preview" / "reel.mp4")
    music, credit = (sys.argv[3] if len(sys.argv) > 3 else None), ""
    if music == "auto":
        music, credit = pick_music(json.loads((Path(post_dir) / "post.json").read_text()).get("mood"))
        print("Music:", music.name if music else "none", "| credit line:", credit or "(none needed)")
    print("Wrote", make_reel(post_dir, out, music=music))
