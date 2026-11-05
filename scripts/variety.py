"""Keep the account varied without forcing weak stories.

Shared by plan_day.py (which hands the daily run a subject for each story and shows what was
published lately) and validate.py (which checks one day's stories against each other).

The rules are deliberately soft. Same-day clashes are errors, but any story can carry a plain
sentence in its `variety_exception` field to say "this one is clearly the best story I found".
validate.py then accepts it and prints the reason, so an exception is never silent and the run is
never trapped into publishing something weak just to satisfy a rule.
"""
import itertools
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The run labels posts with free text. Fold the obvious synonyms together so "ai" and "tech"
# count as one subject when looking at what was published lately.
CATEGORY_ALIASES = {
    "ai": "tech", "robots": "tech", "technology": "tech", "computing": "tech",
    "invention": "inventions", "engineering": "inventions",
    "animal": "animals", "wildlife": "animals",
    "earth": "nature", "oceans": "nature", "environment": "nature",
    "medicine": "health", "archaeology": "history",
}

# Hosts that are a shared service, not one publisher: two stories citing doi.org are not
# drawing on the same organization.
SHARED_HOSTS = {"doi.org", "archive.org", "wikipedia.org", "wikimedia.org", "youtube.com", "jstor.org"}

# Words skipped when comparing how two headlines open ("The number..." vs "The kilogram...").
STOPWORDS = {"the", "a", "an", "this", "that", "these", "those", "in", "on", "at", "of", "to", "it",
             "its", "is", "for", "and", "but", "how", "why", "what", "when", "one", "his", "her", "their"}

MIN_EXCEPTION_CHARS = 15


def canon_category(category):
    c = (category or "").strip().lower()
    return CATEGORY_ALIASES.get(c, c)


def registered_domain(url):
    """nasa.gov for science.nasa.gov, images.nasa.gov and www.nasa.gov alike."""
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0].split(":")[0]
    host = re.sub(r"^www\.", "", host)
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "ac", "gov", "net", "edu"):
        return ".".join(parts[-3:])        # bbc.co.uk, ox.ac.uk
    return ".".join(parts[-2:])


def source_domains(post):
    found = set()
    for src in post.get("sources", []):
        domain = registered_domain(src.get("url", ""))
        if domain and domain not in SHARED_HOSTS:
            found.add(domain)
    return found


def _lead_word(text):
    """First word that is not a filler word, lower case."""
    for word in re.findall(r"[a-z0-9']+", (text or "").lower()):
        if word not in STOPWORDS:
            return word
    return ""


def _last_sentence(text):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if p.strip()]
    return parts[-1] if parts else ""


def cover_of(post):
    slides = post.get("slides") or []
    return ((slides[0].get("headline") or "") if slides else "").strip()


def end_of(post):
    slides = post.get("slides") or []
    return ((slides[-1].get("text") or "") if slides else "").strip()


def exception_of(post):
    reason = (post.get("variety_exception") or "").strip()
    return reason if len(reason) >= MIN_EXCEPTION_CHARS else ""


def recent_posts(limit=12, exclude_dates=()):
    """The newest posts in queue/, oldest first, as small summaries."""
    rows = []
    for path in (ROOT / "queue").glob("*/*/post.json"):
        if path.parent.parent.name in ("sample", "demo"):
            continue
        try:
            post = json.loads(path.read_text())
        except Exception:
            continue
        if str(post.get("date", "")) in exclude_dates:
            continue
        rows.append({
            "date": str(post.get("date", "")), "id": str(post.get("id", "")),
            "category": canon_category(post.get("category")),
            "cover": cover_of(post), "end": end_of(post), "domains": sorted(source_domains(post)),
        })
    rows.sort(key=lambda r: (r["date"], r["id"]))
    return rows[-limit:]


def day_problems(day_posts):
    """Compare the stories of ONE day with each other.

    day_posts: list of (folder_name, post_dict) for the day's stories.
    Returns (errors, notes). A clash is waived when either story carries a variety_exception.
    """
    errors, notes = [], []
    for (name_a, a), (name_b, b) in itertools.combinations(day_posts, 2):
        clashes = []
        shared = source_domains(a) & source_domains(b)
        if shared:
            clashes.append("both use %s as a source" % ", ".join(sorted(shared)))
        cat_a, cat_b = canon_category(a.get("category")), canon_category(b.get("category"))
        if cat_a and cat_a == cat_b:
            clashes.append("both are about '%s'" % cat_a)
        for what, text_a, text_b in (
            ("covers open the same way", cover_of(a), cover_of(b)),
            ("covers close the same way", _last_sentence(cover_of(a)), _last_sentence(cover_of(b))),
            ("closing slides open the same way", end_of(a), end_of(b)),
        ):
            lead_a, lead_b = _lead_word(text_a), _lead_word(text_b)
            if lead_a and lead_a == lead_b:
                clashes.append("%s ('%s')" % (what, lead_a))
        if not clashes:
            continue
        message = "%s and %s: %s" % (name_a, name_b, "; ".join(clashes))
        reason = exception_of(a) or exception_of(b)
        if reason:
            notes.append("allowed by variety_exception (\"%s\"): %s" % (reason, message))
        else:
            errors.append(message + ". Change one (another source, subject or wording), or if one story is "
                          "clearly the best you found, say why in its \"variety_exception\" field")
    return errors, notes


def history_notes(day_posts, day_dates, window=12, threshold=4):
    """Gentle heads-up (never an error) when a subject has been used a lot lately."""
    recent = recent_posts(window, exclude_dates=tuple(day_dates))
    counts = {}
    for row in recent:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    notes = []
    for name, post in day_posts:
        cat = canon_category(post.get("category"))
        if cat and counts.get(cat, 0) >= threshold:
            notes.append("%s is about '%s', which was %d of the %d posts before this day. Fine if it is "
                         "the best story; check that nothing as good exists in a quieter subject."
                         % (name, cat, counts[cat], len(recent)))
    return notes
