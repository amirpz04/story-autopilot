"""Draw today's research plan at random, so every run starts somewhere different.

Usage: python3 scripts/plan_day.py [--stories 3] [--seed anything]

The daily run must start here. Left to its own habits the run kept going back to the same
feed (7 of the first 9 stories came from ScienceDaily) and, later, to the same subject (a day
of three NASA stories). This script deals the run a hand it did not choose: for each story a
lane, a SUBJECT, an angle, and the places to start looking, drawn at random from a wide pool.

Subjects are drawn with a thumb on the scale: a subject that filled a lot of the recent posts
comes up rarely, a subject that has been quiet comes up often, and no two stories in a day get
the same one. It is a steer, not a trap: the plan also deals backup subjects, and a clearly
better story elsewhere can be taken if the post says why (`variety_exception`, see variety.py).

The draw is reseeded on every run (date + clock + a random number), so a second run on the
same day explores different ground instead of repeating the first one's dead ends.
"""
import argparse
import json
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import variety

ROOT = Path(__file__).resolve().parent.parent
RECENT_POSTS = 12      # how far back "lately" looks, in posts

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
FEED_BY_NAME = dict(NEWS_FEEDS)

# Google News runs in any language: the story nobody in English has seen yet.
# These are hunting grounds only. The post is always written in US English for a US reader
# (ROUTINE.md section 1) - a Japanese feed is a source of stories, never a change of audience.
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

# Lane A subjects: what a news story should be ABOUT. Each has a plain description for the run,
# feeds that actually carry that subject, and Google News queries to try. The keys are the values
# the run writes into post.json "category" (variety.py folds near-synonyms together).
NEWS_SUBJECTS = {
    "space": (
        "space and astronomy: telescopes, planets, missions, astronauts, sky events",
        ["EurekAlert space", "NASA news", "ESA news", "r/space", "Phys.org"],
        ["telescope spotted", "astronomers puzzled", "space mission first"],
    ),
    "animals": (
        "animals and wildlife: strange behavior, new species, rare sightings",
        ["EurekAlert biology", "r/Awwducational", "r/natureisfuckinglit", "New Scientist", "Smithsonian Magazine"],
        ["new species discovered", "rare animal filmed", "strange animal behavior study"],
    ),
    "nature": (
        "the living and physical Earth: oceans, plants, weather, geology, ecosystems",
        ["EurekAlert earth science", "NOAA news", "r/natureisfuckinglit", "Atlas Obscura", "Smithsonian Magazine"],
        ["deep sea discovery", "oldest tree plant record", "geology surprising discovery"],
    ),
    "health": (
        "the human body and medicine: surprising findings, new treatments",
        ["EurekAlert medicine", "r/science", "New Scientist", "ScienceDaily top"],
        ["surprising health study", "new treatment first patients", "human body discovery"],
    ),
    "tech": (
        "technology, AI and robots: what they can do now, what went wrong",
        ["IEEE Spectrum", "Ars Technica", "Hacker News front page", "r/artificial", "r/technology", "r/Futurology"],
        ["world first robot", "AI surprised researchers", "software bug outage cause"],
    ),
    "inventions": (
        "inventions and engineering: odd gadgets, records, clever solutions, new materials",
        ["IEEE Spectrum", "Hackaday", "r/EngineeringPorn", "r/gadgets", "EurekAlert technology"],
        ["invention student built", "engineers built record", "new material discovered"],
    ),
    "science": (
        "science beyond space and biology: physics, chemistry, the brain, psychology, measurement",
        ["EurekAlert technology", "Phys.org", "Nature news", "New Scientist", "r/science", "ScienceDaily top"],
        ["experiment result", "scientists puzzled", "unexpected finding study"],
    ),
    "history": (
        "history and archaeology: what was found, what it changes about the story we know",
        ["Smithsonian Magazine", "Atlas Obscura", "r/todayilearned", "Phys.org"],
        ["archaeologists found", "oldest ever found", "historians discover"],
    ),
}

# --- Lane B: evergreen angles --------------------------------------------------
# No news hook needed. Old is fine. The hook is the surprising fact itself.
# Each angle carries the subject it naturally belongs to, so the subject draw and the angle draw
# are one decision.
EVERGREEN_ANGLES = [
    ("business", "the origin of a company everyone knows (the near-failure, the pivot, the real numbers)"),
    ("business", "how someone made a fortune from one unlikely decision"),
    ("business", "how someone lost a fortune, and what exactly went wrong"),
    ("inventions", "an everyday object with a backstory nobody expects"),
    ("inventions", "an accidental invention: what the inventor was actually trying to do"),
    ("people", "a forgotten inventor who got none of the credit"),
    ("tech", "how a technology people use daily actually works under the hood"),
    ("tech", "a famous software bug or outage and what it cost"),
    ("tech", "the story behind a programming language, a file format or a standard"),
    ("inventions", "a machine or building that broke a record, and the problem it had to solve"),
    ("inventions", "a bridge, tunnel, dam or ship with a hard engineering story"),
    ("history", "the origin of a game, toy or sport people still play"),
    ("history", "a language or writing system with a strange history"),
    ("history", "a currency, unit or calendar and why it is the way it is"),
    ("science", "an expedition or experiment that went differently than planned"),
    ("people", "a person with a documented, genuinely strange life story"),
    ("tech", "the first version of something familiar, and how bad it was"),
    ("business", "a product that failed, then came back and won"),
    ("nature", "an animal, plant or natural record that still astonishes"),
    ("history", "a map, a book or a document that changed something"),
    ("history", "a food or drink everyone consumes, and where it actually came from"),
    ("business", "a rivalry between two companies or two inventors"),
    ("inventions", "something built for one purpose that is now used for a completely different one"),
    ("history", "a law, rule or safety standard and the documented chain from one disaster to the rule (not 'only because of')"),
    ("business", "a decision that looked like a mistake and made millions, with the real figures"),
    ("people", "someone who survived or solved something against the odds, told from documented accounts"),
    ("tech", "a number, standard or default everyone uses and the person who chose it"),
    ("health", "a medical discovery made by accident, and the named people involved"),
    ("health", "an odd fact about the human body that doctors can explain and most people never learned"),
    ("space", "a space mission that nearly failed and the improvised fix that saved it"),
    ("space", "a strange fact about the Moon, Mars, the Sun or Earth's orbit that still astonishes"),
    ("animals", "an animal with a documented extreme ability, and how scientists found out"),
    ("history", "a heist, hoax or forgery and the one detail that exposed it"),
    ("inventions", "an engineering failure and the documented changes it forced"),
    ("nature", "a natural place or event that looks impossible, and how it actually works"),
    ("science", "something everyone was taught that later turned out different (only with strong sources)"),
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


def weighted_pick(rng, items, weights):
    """One item, chosen with probability proportional to its weight."""
    total = float(sum(weights))
    point = rng.random() * total
    running = 0.0
    for item, weight in zip(items, weights):
        running += weight
        if point <= running:
            return item
    return items[-1]


def subject_weights(recent):
    """How likely each subject is to be dealt: quiet ones often, busy ones rarely.

    A subject that filled 5 of the last 12 posts gets about 1/36 of the weight of one that
    filled none. Nothing is ever ruled out, so a subject can still come back if it earns it.
    """
    counts = Counter(row["category"] for row in recent)
    return counts, (lambda cat: 1.0 / (1 + counts[cat]) ** 2)


def deal(stories, seed=None, recent=None):
    rng = random.Random(seed if seed is not None else "%s-%s-%s" % (
        datetime.now(timezone.utc).isoformat(), time.time(), random.random()))
    recent = recent if recent is not None else variety.recent_posts(RECENT_POSTS)
    counts, weight = subject_weights(recent)

    # How many evergreen: never zero, never all, when there is room for a mix.
    if stories <= 1:
        evergreen = rng.choice([0, 1])
    else:
        evergreen = rng.randint(1, max(1, stories - 1))

    lanes = ["B"] * evergreen + ["A"] * (stories - evergreen)
    rng.shuffle(lanes)

    starts = rng.sample(EVERGREEN_STARTS, min(len(EVERGREEN_STARTS), stories * 2))
    angle_pool = list(EVERGREEN_ANGLES)
    used_subjects, used_feeds = [], set()

    plan = []
    for i, lane in enumerate(lanes, 1):
        if lane == "A":
            options = [c for c in NEWS_SUBJECTS if c not in used_subjects] or list(NEWS_SUBJECTS)
            subject = weighted_pick(rng, options, [weight(c) for c in options])
            description, feed_names, queries = NEWS_SUBJECTS[subject]
            feeds = [(n, FEED_BY_NAME[n]) for n in feed_names if n in FEED_BY_NAME]
            fresh = [f for f in feeds if f[0] not in used_feeds] or feeds
            feed = rng.choice(fresh)
            rest = [f for f in feeds if f != feed]
            backup = rng.choice(rest) if rest else feed
            used_feeds.update([feed[0], backup[0]])
            country, params = rng.choice(NEWS_COUNTRIES)
            query = rng.choice(queries)
            plan.append({
                "n": i, "lane": "A (news, last 72 h)", "subject": subject,
                "lean": description,
                "start": "%s  %s" % feed,
                "then": "%s  %s" % backup,
                "wildcard": "Google News %s: https://news.google.com/rss/search?q=%s+when:2d&%s" % (
                    country, query.replace(" ", "+"), params),
            })
        else:
            options = [a for a in angle_pool if a[0] not in used_subjects] or angle_pool
            per_subject = Counter(a[0] for a in options)
            angle = weighted_pick(rng, options, [weight(a[0]) / per_subject[a[0]] for a in options])
            angle_pool.remove(angle)
            subject = angle[0]
            start = starts.pop() if starts else rng.choice(EVERGREEN_STARTS)
            backup = starts.pop() if starts else start
            plan.append({
                "n": i, "lane": "B (evergreen, any age)", "subject": subject,
                "lean": angle[1],
                "start": "%s  %s" % start,
                "then": "%s  %s" % backup,
                "wildcard": "or any subject of your own that fits the angle - there is no topic limit",
            })
        used_subjects.append(subject)

    # Backup subjects: where to turn if an assigned subject has nothing good after a fair look.
    everything = sorted(set(NEWS_SUBJECTS) | {a[0] for a in EVERGREEN_ANGLES})
    pool = [c for c in everything if c not in used_subjects]
    backups = []
    while pool and len(backups) < 3:
        pick = weighted_pick(rng, pool, [weight(c) for c in pool])
        backups.append(pick)
        pool.remove(pick)
    return plan, rng, backups, counts


def print_mirror(recent, counts):
    if not recent:
        return
    print()
    print("WHAT THE LAST %d POSTS WERE (a mirror - ROUTINE.md sections 4 and 9.3)" % len(recent))
    print("-" * 70)
    for row in recent:
        print("  [%s] cover: %s" % (row["category"] or "?", row["cover"]))
        print("        end: %s" % row["end"])
    print()
    subjects = ", ".join("%s x%d" % (c, n) for c, n in counts.most_common())
    print("  Subjects lately: %s" % subjects)
    domains = Counter(d for row in recent for d in row["domains"])
    print("  Sources lately : %s" % ", ".join("%s x%d" % (d, n) for d, n in domains.most_common(8)))

    words = lambda t: re.findall(r"[a-z0-9']+", t.lower())
    firsts = Counter(w[0] for w in (words(r["cover"]) for r in recent) if w)
    pairs = Counter(" ".join(w[:2]) for w in (words(r["cover"]) for r in recent) if len(w) > 1)
    ends = Counter(" ".join(w[:3]) for w in (words(r["end"]) for r in recent) if len(w) > 2)
    repeated = ["'%s' x%d" % (w, n) for w, n in firsts.most_common() if n >= 2]
    repeated += ["'%s...' x%d" % (p, n) for p, n in pairs.most_common() if n >= 2]
    if repeated:
        print("  Cover openers that keep coming back: " + ", ".join(repeated[:6]))
    repeated_ends = ["'%s...' x%d" % (p, n) for p, n in ends.most_common() if n >= 2]
    if repeated_ends:
        print("  Ending openers that keep coming back: " + ", ".join(repeated_ends[:4]))
    lengths = [len(words(r["cover"])) for r in recent]
    questions = sum(1 for r in recent if "?" in r["cover"])
    print("  Questions: %d of %d covers. Average length: %.1f words." % (
        questions, len(recent), sum(lengths) / float(len(lengths))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", type=int, default=None)
    ap.add_argument("--seed", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    config = json.loads((ROOT / "config.json").read_text())
    stories = args.stories or int(config.get("stories_per_day", 3))
    recent = variety.recent_posts(RECENT_POSTS)
    plan, rng, backups, counts = deal(stories, args.seed, recent)

    if args.json:
        print(json.dumps({"plan": plan, "backup_subjects": backups}, indent=2))
        return

    print("TODAY'S RESEARCH PLAN  (%d stories, drawn at random - follow it)" % stories)
    print("=" * 70)
    for p in plan:
        print()
        print("STORY %d - lane %s" % (p["n"], p["lane"]))
        print("  SUBJECT  : %s" % p["subject"].upper())
        print("  about    : %s" % p["lean"])
        print("  start at : %s" % p["start"])
        print("  if thin  : %s" % p["then"])
        print("  wildcard : %s" % p["wildcard"])
    print()
    print("  Backup subjects (if an assigned one has nothing good after a fair look): %s" % ", ".join(backups))
    print_mirror(recent, counts)
    print()
    print("=" * 70)
    print("RULES FOR TODAY")
    print("  - Each story has a SUBJECT above. Find the best story you can in it. The draw favors subjects")
    print("    that have been quiet lately, so following it is what keeps the account varied.")
    print("  - It is a steer, not a trap. Nothing good after two entry points? Use a backup subject. A clearly")
    print("    better story from somewhere else? Take it and say why in `variety_exception` in post.json.")
    print("    Never publish a weaker story just to fit a subject, and never two stories on one subject today.")
    print("  - No two stories from the same organization today (nasa.gov counts once, whatever the subdomain).")
    print("    Same exception rule applies.")
    print("  - Choose the story first, pictures second. An archive with lots of pictures (NASA's, say) is never a")
    print("    reason to pick a subject. Thin pictures? Use labelled stock for generic slides or take another story.")
    print("  - Story test (ROUTINE.md 5.1): one-sentence surprise, friend test, 5+ beats, true, 3+ pictures. Fail one = drop it.")
    print("  - Claim check (ROUTINE.md 6): every 'because', 'first', 'only', count and order of events needs a source that says so.")
    print("  - Small is fine. A quiet, specific, surprising story beats a big boring one.")
    print("    Do NOT hold out for something groundbreaking; that is how runs end with one story.")
    print("  - If an entry point is thin after a few minutes, move to the next one in this plan.")
    print("    Do not drift back to a feed you have used before.")
    print("  - Covers: no two stories today share an opening word, a closing pattern, or an ending opener,")
    print("    and none could sit unnoticed among the covers above. Hooks and voice: ROUTINE.md section 9.3.")
    print("  - Pictures: try %s first." % rng.choice(IMAGE_FIRST_STOP))
    print("    Wikimedia is one option among several, not the default.")
    print("  - You must finish with %d stories. See ROUTINE.md section 12." % stories)


if __name__ == "__main__":
    main()
