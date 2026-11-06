"""Find free songs for a mood on Mixkit (free for videos, no credit needed), so the daily run can add one when the library has none.

Usage: python3 scripts/find_music.py MOOD [--limit 8]        MOOD = hype | playful | tense | mysterious | inspiring | chill
       python3 scripts/find_music.py --page genre/hip-hop     any Mixkit page: genre/hip-hop, genre/electronic, mood/happy, mood/dark, ...

Prints each song with the exact command that adds it (the song is linked, not copied). Mixkit is listened to by name and genre only:
pick songs whose genre and title suit the story, then add with the mood you need.
"""
import json
import re
import subprocess
import sys

PAGES = {
    "hype": ["mood/exciting", "genre/hip-hop", "genre/electronic"],
    "playful": ["mood/quirky", "mood/happy"],
    "tense": ["mood/dark", "mood/dramatic"],
    "mysterious": ["mood/dark", "genre/electronic", "genre/cinematic"],
    "inspiring": ["mood/uplifting", "genre/cinematic"],
    "chill": ["genre/electronic", "mood/sad"],
}


def tracks(page):
    html = subprocess.run(["curl", "-sL", "-m", "30", "https://mixkit.co/free-stock-music/%s/" % page], capture_output=True, text=True).stdout
    out = []
    for name, genre, artist, dur, url in re.findall(
            r'\{"@id":"[^"]*","@type":"MusicRecording","name":"([^"]+)","genre":"([^"]*)","byArtist":"([^"]*)","duration":"([^"]*)","url":"([^"]+)"', html):
        m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", dur)
        seconds = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        out.append((name.encode().decode("unicode_escape") if "\\u" in name else name, genre, artist, seconds, url))
    return out


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 8
    if "--page" in args:
        pages, mood = [args[args.index("--page") + 1]], "MOOD"
    elif args and args[0] in PAGES:
        pages, mood = PAGES[args[0]], args[0]
    else:
        print(__doc__)
        sys.exit(1)
    seen = set()
    for page in pages:
        for name, genre, artist, seconds, url in tracks(page)[:limit]:
            if url in seen or seconds < 45:
                continue
            seen.add(url)
            print('%s | %s | %s | %ds\n  python3 scripts/control.py add_music %s "%s (%s) | | Mixkit Free License | %s"' % (name, genre, artist, seconds, url, name, artist, mood))


if __name__ == "__main__":
    main()
