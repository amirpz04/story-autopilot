"""Fail (so GitHub emails you) if today's posts were never queued.

Runs before the first posting time. A failed run = the morning routine didn't deliver.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
config = json.loads((ROOT / "config.json").read_text())
today = datetime.now(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d")
posts = list((ROOT / "queue" / today).glob("*/post.json"))
print("%s: %d post(s) queued for today" % (today, len(posts)))
if not posts:
    print("No posts were queued today: the daily Claude routine did not run or did not finish.")
    sys.exit(1)
