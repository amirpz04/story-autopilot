"""Draw today's research plan at random, so every run starts somewhere different.

Usage: python3 scripts/plan_day.py [--stories 3] [--seed anything]

The daily run must start here. Left to its own habits the run kept going back to the same
feed (7 of the first 9 stories came from ScienceDaily), which is why the account felt
repetitive. This script deals the run a hand it did not choose: for each story a lane, an
angle, and the places to start looking, drawn at random from a wide pool. The run follows
the plan; if an entry point turns up nothing good, it draws the next one rather than
falling back to its favourite feed.

The draw is reseeded on every run (date + clock + a random number), so a second run on the
same day explores different ground instead of repeating the first one's dead ends.
"""
import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Lane A: news entry points -------------------------------------------------
# Live feeds first: web search lags by days. Each entry is a place to START, not a limit.
NEWS_FEEDS = [
    ("EurekAlert technology", "https://www.eurekalert.org/rss/technology_engineering.xml"),
    ("EurekAlert space", "https://www.eurekalert.org/rss/space_planetary.xml"),
    ("EurekAlert biology", "https://www.eurekalert.org/rss/biology.xml"),
    ("EurekAlert earth science", "https://www.eurekalert.org/rss/earth_science.xml"),
    ("EurekAlert medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("ScienceDaily top", "https://www.sciencedaily.com/rss/top.xml"),
    ("Phys.org", "https://phys.org/rss-feed/"),
    ("NASA news", "https://www.nasa.gov/news-release/feed/"),
    ("ESA news", "https://www.esa.int/rssfeed/Our_Activities/Space_News"),
    ("NOAA news", "https://www.noaa.gov/news-releases.xml"),
    ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/feed.rss"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Hacker News front page", "https://hnrss.org/frontpage?points=150"),
    ("Nature news", "https://www.nature.com/nature.rss"),
    ("New Scientist", "https://www.newscientist.com/feed/home/"),
    ("Smithsonian Magazine", "https://www.smithsonianmag.com/rss/latest_articles/"),
    ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest"),
    ("Hackaday", "https://hackaday.com/feed/"),
    ("r/science", "https://www.reddit.com/r/science/top.json?t=day&limit=25"),
    ("r/space", "https://www.reddit.com/r/space/top.json?t=day&limit=25"),
    ("r/technology", "https://www.reddit.com/r/technology/top.json?t=day&limit=25"),
    ("r/Futurology", "https://www.reddit.com/r/Futurology/top.json?t=day&limit=25"),
    ("r/artificial", "https://www.reddit.com/r/artificial/top.json?t=day&limit=25"),
    ("r/gadgets", "https://www.reddit.com/r/gadgets/top.json?t=day&limit=25"),
    ("r/EngineeringPorn", "https://www.reddit.com/r/EngineeringPorn/top.json?t=day&limit=25"),
    ("r/natureisfuckinglit", "https://www.reddit.com/r/natureisfuckinglit/top.json?t=day&limit=25"),
    ("r/Awwducational", "https://www.reddit.com/r/Awwducational/top.json?t=day&limit=25"),
    ("r/biology", "https://www.reddit.com/r/biology/top.json?t=day&limit=25"),
    ("r/todayilearned", "https://www.reddit.com/r/todayilearned/top.json?t=day&limit=25"),
]

# Google News runs in any language: the story nobody in English has seen yet.
NEWS_COUNTRIES = [
    ("Japan", "hl=ja&gl=JP&ceid=JP:ja"),
    ("South Korea", "hl=ko&gl=KR&ceid=KR:ko"),
    ("Germany", "hl=de&gl=DE&ceid=DE:de"),
    ("India", "hl=en-IN&gl=IN&ceid=IN:en"),
    ("Brazil", "hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("France", "hl=fr&gl=FR&ceid=FR:fr"),
    ("Spain", "hl=es&gl=ES&ceid=ES:es"),
    ("Netherlands", "hl=nl&gl=NL&ceid=NL:nl"),
    ("Sweden", "hl=sv&gl=SE&ceid=SE:sv"),
    ("Turkey", "hl=tr&gl=TR&ceid=TR:tr"),
    ("Italy", "hl=it&gl=IT&ceid=IT:it"),
    ("Poland", "hl=pl&gl=PL&ceid=PL:pl"),
    ("Indonesia", "hl=id&gl=ID&ceid=ID:id"),
    ("Mexico", "hl=es-419&gl=MX&ceid=MX:es-419"),
]

NEWS_QUERIES = [
    "new species discovered", "world first robot", "strange discovery", "record broken science",
    "archaeologists found", "deep sea discovery", "AI surprised researchers", "invention student built",
    "telescope spotted", "fossil discovery", "rare animal filmed", "engineers built", "experiment result",
    "scientists puzzled", "oldest ever found", "largest ever recorded", "unexpected finding study",
]

# --- Lane B: evergreen angles --------------------------------------------------
# No news hook needed. Old is fine. The hook is the surprising fact itself.
EVERGREEN_ANGLES = [
    "the origin of a company everyone knows (the near-failure, the pivot, the real numbers)",
    "how someone made a fortune from one unlikely decision",
    "how someone lost a fortune, and what exactly went wrong",
    "an everyday object with a backstory nobody expects",
    "an accidental invention: what the inventor was actually trying to do",
    "a forgotten inventor who got none of the credit",
    "how a technology people use daily actually works under the hood",
    "a famous software bug or outage and what it cost",
    "the story behind a programming language, a file format or a standard",
    "a machine or building that broke a record, and the problem it had to solve",
    "a bridge, tunnel, dam or ship with a hard engineering story",
    "the origin of a game, toy or sport people still play",
    "a language or writing system with a strange history",
    "a currency, unit or calendar and why it is the way it is",
    "an expedition or experiment that went differently than planned",
    "a person with a documented, genuinely strange life story",
    "the first version of something familiar, and how bad it was",
    "a product that failed, then came back and won",
    "an animal, plant or natural record that still astonishes",
    "a map, a book or a document that changed something",
    "a food or drink everyone consumes, and where it actually came from",
    "a rivalry between two companies or two inventors",
    "something built for one purpose that is now used for a completely different one",
    "a law, rule or safety standard written because of one specific disaster",
]

EVERGREEN_STARTS = [
    ("Wikipedia 'On this day' then trace to real sources", "https://en.wikipedia.org/wiki/Wikipedia:On_this_day"),
    ("Smithsonian Magazine history", "https://www.smithsonianmag.com/history/"),
    ("Atlas Obscura", "https://www.atlasobscura.com/"),
    ("IEEE Spectrum history", "https://spectrum.ieee.org/history-of-technology"),
    ("Internet Archive scans of old books and manuals", "https://archive.org/"),
    ("Library of Congress digital collections", "https://www.loc.gov/collections/"),
    ("r/todayilearned (leads only, always trace the source)", "https://www.reddit.com/r/todayilearned/top.json?t=week&limit=50"),
    ("r/AskHistorians (leads only)", "https://www.reddit.com/r/AskHistorians/top.json?t=week&limit=25"),
    ("Company history pages and annual reports / SEC filings", "https://www.sec.gov/edgar/search/"),
    ("Museum collections (Science Museum, Deutsches Museum, Computer History Museum)", "https://computerhistory.org/"),
    ("Hackaday retro and teardown articles", "https://hackaday.com/category/retrotechtacular/"),
    ("99% Invisible archive", "https://99percentinvisible.org/episodes/"),
    ("Low-tech Magazine", "https://solar.lowtechmagazine.com/"),
    ("Public Domain Review", "https://publicdomainreview.org/"),
]

CATEGORIES = ["space", "animals", "nature", "tech", "ai", "science", "health",
              "inventions", "history", "business", "people"]

IMAGE_FIRST_STOP = [
    "NASA image library (images.nasa.gov) - space, Earth, aviation",
    "ESA / ESO / NOIRLab press images - space and telescopes",
    "Wikimedia Commons via scripts/find_images.py - almost any subject",
    "Smithsonian Open Access (si.edu/openaccess) - objects, specimens, history",
    "Library of Congress (loc.gov) - historical photos, maps, prints",
    "The Met Open Access / Rijksmuseum - art, objects, period pictures",
    "NOAA / USGS / US Fish & Wildlife - nature, weather, geology, animals",
    "Internet Archive book scans - diagrams and old illustrations",
]


def deal(stories, seed=None):
    rng = random.Random(seed if seed is not None else "%s-%s-%s" % (
        datetime.now(timezone.utc).isoformat(), time.time(), random.random()))

    # How many evergreen: never zero, never all, when there is room for a mix.
    if stories <= 1:
        evergreen = rng.choice([0, 1])
    else:
        evergreen = rng.randint(1, max(1, stories - 1))

    lanes = ["B"] * evergreen + ["A"] * (stories - evergreen)
    rng.shuffle(lanes)

    news_feeds = rng.sample(NEWS_FEEDS, min(len(NEWS_FEEDS), stories * 2))
    angles = rng.sample(EVERGREEN_ANGLES, min(len(EVERGREEN_ANGLES), stories * 2))
    starts = rng.sample(EVERGREEN_STARTS, min(len(EVERGREEN_STARTS), stories * 2))
    cats = rng.sample(CATEGORIES, min(len(CATEGORIES), stories))

    plan = []
    for i, lane in enumerate(lanes, 1):
        if lane == "A":
            country, params = rng.choice(NEWS_COUNTRIES)
            query = rng.choice(NEWS_QUERIES)
            feed = news_feeds.pop()
            backup = news_feeds.pop() if news_feeds else feed
            plan.append({
                "n": i, "lane": "A (news, last 72 h)",
                "lean": "lean %s, but take the better story if the feed offers one" % cats[i - 1],
                "start": "%s  %s" % (feed[0], feed[1]),
                "then": "%s  %s" % (backup[0], backup[1]),
                "wildcard": "Google News %s: https://news.google.com/rss/search?q=%s+when:2d&%s" % (
                    country, query.replace(" ", "+"), params),
            })
        else:
            angle = angles.pop()
            start = starts.pop()
            backup = starts.pop() if starts else start
            plan.append({
                "n": i, "lane": "B (evergreen, any age)",
                "lean": angle,
                "start": "%s  %s" % (start[0], start[1]),
                "then": "%s  %s" % (backup[0], backup[1]),
                "wildcard": "or any subject of your own that fits the angle - there is no topic limit",
            })
    return plan, rng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", type=int, default=None)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    config = json.loads((ROOT / "config.json").read_text())
    stories = args.stories or int(config.get("stories_per_day", 3))
    plan, rng = deal(stories, args.seed)

    if args.json:
        print(json.dumps(plan, indent=2))
        return

    print("TODAY'S RESEARCH PLAN  (%d stories, drawn at random - follow it)" % stories)
    print("=" * 70)
    for p in plan:
        print()
        print("STORY %d - lane %s" % (p["n"], p["lane"]))
        print("  angle    : %s" % p["lean"])
        print("  start at : %s" % p["start"])
        print("  if thin  : %s" % p["then"])
        print("  wildcard : %s" % p["wildcard"])
    print()
    print("=" * 70)
    print("RULES FOR TODAY")
    print("  - No two stories from the same website. Ever. If two land on one site, redraw one.")
    print("  - Small is fine. A quiet, specific, surprising story beats a big boring one.")
    print("    Do NOT hold out for something groundbreaking; that is how runs end with one story.")
    print("  - If an entry point is thin after a few minutes, move to the next one in this plan.")
    print("    Do not drift back to a feed you have used before.")
    print("  - Pictures: try %s first." % rng.choice(IMAGE_FIRST_STOP))
    print("    Wikimedia is one option among several, not the default.")
    print("  - You must finish with %d stories. See ROUTINE.md section 9." % stories)


if __name__ == "__main__":
    main()
