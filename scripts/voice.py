"""Read lines aloud with Kokoro (free, open-source, runs offline; https://huggingface.co/hexgrad/Kokoro-82M).

Usage: python scripts/voice.py lines.json out_dir VOICE [SPEED]
lines.json is a list of strings. Writes out_dir/line_00.wav, ... (24 kHz mono) and prints a JSON list of their
lengths in seconds. Run as its own process so make_reel.py can use another Python (TTS_PYTHON) if needed.
Needs: pip install kokoro soundfile (and torch; on Linux the CPU build is enough).
"""
import json
import re
import sys
from pathlib import Path


def speakable(text):
    """Small fixes so numbers and symbols are read the way a person would say them."""
    text = re.sub(r"(\d),(\d{3})", r"\1\2", text)                 # 1,045 -> 1045 (read as "one thousand forty-five")
    text = text.replace("%", " percent").replace("&", " and ").replace("U.K.", "U K").replace("U.S.", "U S")
    text = re.sub(r"\$(\d[\d.]*)\s*(million|billion|trillion)", r"\1 \2 dollars", text)
    text = re.sub(r"\$(\d[\d.]*)", r"\1 dollars", text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    lines = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    voice = sys.argv[3]
    speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.05
    out.mkdir(parents=True, exist_ok=True)
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
    print(json.dumps(lengths))


if __name__ == "__main__":
    main()
