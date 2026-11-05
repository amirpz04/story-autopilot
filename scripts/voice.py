"""Read lines aloud for the Reel narrator. Free, no account and no key.

Usage: python scripts/voice.py lines.json out_dir VOICE [SPEED]
lines.json is a list of strings. Writes out_dir/line_00.wav, ... (24 kHz mono) and prints a JSON list of their
lengths in seconds. The last line written to stderr says which voice was used.

Voices:
- names like en-US-AndrewMultilingualNeural: Microsoft's neural voices through the `edge-tts` package (the same service
  the Edge browser's "Read aloud" uses). Most natural, but it is an unofficial route: it needs internet and could change
  or be blocked one day. If it fails, the lines are read by Kokoro instead.
- names like am_michael: Kokoro-82M (open source, offline, https://huggingface.co/hexgrad/Kokoro-82M). Needs `kokoro`,
  `soundfile` and torch.
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

FALLBACK = "am_michael"          # Kokoro voice used when the preferred voice cannot be reached


def speakable(text):
    """Small fixes so numbers and symbols are read the way a person would say them."""
    text = re.sub(r"(\d),(\d{3})", r"\1\2", text)                 # 1,045 -> 1045
    text = text.replace("%", " percent").replace("&", " and ").replace("U.K.", "U K").replace("U.S.", "U S")
    text = re.sub(r"\$(\d[\d.]*)\s*(million|billion|trillion)", r"\1 \2 dollars", text)
    text = re.sub(r"\$(\d[\d.]*)", r"\1 dollars", text)
    return re.sub(r"\s+", " ", text).strip()


def wav_length(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return round(float(out), 3)


def with_edge(lines, out, voice, speed):
    import edge_tts
    rate = "%+d%%" % max(-25, min(25, round((speed - 1) * 100)))

    async def one(i, line):
        mp3, wav = out / ("line_%02d.mp3" % i), out / ("line_%02d.wav" % i)
        last = None
        for attempt in range(3):
            try:
                await edge_tts.Communicate(speakable(line), voice, rate=rate).save(str(mp3))
                if mp3.stat().st_size > 800:
                    break
            except Exception as exc:
                last = exc
            await asyncio.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError("edge-tts failed for line %d: %s" % (i, last))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1", str(wav)], check=True)
        return wav_length(wav)

    async def run():
        return [await one(i, line) if line.strip() else 0.1 for i, line in enumerate(lines)]
    return asyncio.run(run())


def with_kokoro(lines, out, voice, speed):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a" if voice[:1] == "a" else "b", repo_id="hexgrad/Kokoro-82M")
    lengths = []
    for i, line in enumerate(lines):
        parts = [audio for _, _, audio in pipe(speakable(line), voice=voice, speed=speed)] if line.strip() else []
        audio = np.concatenate(parts) if parts else np.zeros(2400, dtype="float32")
        sf.write(str(out / ("line_%02d.wav" % i)), audio, 24000)
        lengths.append(round(len(audio) / 24000, 3))
    return lengths


def main():
    lines = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    voice = sys.argv[3]
    speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.05
    out.mkdir(parents=True, exist_ok=True)
    used, lengths = voice, None
    if "-" in voice:                                   # a Microsoft neural voice
        try:
            lengths = with_edge(lines, out, voice, speed)
        except Exception as exc:
            print("edge voice failed (%s); using Kokoro %s" % (str(exc)[:160], FALLBACK), file=sys.stderr)
            used = FALLBACK
    else:
        used = voice
    if lengths is None:
        lengths = with_kokoro(lines, out, used if "-" not in used else FALLBACK, min(speed, 1.1))
    print("used %s" % used, file=sys.stderr)
    print(json.dumps(lengths))


if __name__ == "__main__":
    main()
