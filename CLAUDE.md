# Uncle Facts (@unclefactss): autonomous Instagram story account

> **If you are the daily research run** (the cloud task "Daily stories"), ignore this file and follow `ROUTINE.md` only.
> This file is for maintenance sessions where the owner asks for changes or fixes. **Read all of it before changing anything**,
> then `git pull` (other Claude sessions and the publisher bot push to `main` constantly; never trust a stale working tree).

Posts true stories (science, space, nature, animals, health, tech/AI, inventions, history, how companies/things came to be)
as **image carousels and animated Reels**, fully automatically, to Instagram **@unclefactss** (Creator account, display name
currently "Tech daddy"; owner may change it). Claude researches and writes; scripts render, post and report.
**Audience: the United States, in English** - every posting time is a New York time and every post is written in US English (ROUTINE.md section 0). Foreign-language feeds are used to FIND stories, never to change who the post is for.
Repo (public): github.com/amirpz04/story-autopilot. Dashboard / control panel: https://amirpz04.github.io/story-autopilot/

## 1. How a day works (end to end)
| When (UTC) | What | Code |
|---|---|---|
| 09:15 daily (12:15 Istanbul) | **Research run**: Claude (cloud task "Daily stories", id `trig_015p8XY87MCPiPaEgKXrXyxf`, cloud environment "stories" with full network access, prompt "follow ROUTINE.md exactly for today's run") searches the web, verifies, picks real pictures, writes `queue/<New York date>/<NN>/post.json` for `stories_per_day` stories (+ spares), appends `state/history.jsonl`, runs `validate.py` and `check_images.py`, pushes to `main`. Runs on claude-sonnet-5-5 per the Nov 1 run log (the UI shows "Default . Opus 5.5"; check with `RemoteTrigger get_run_log`). Took 14 min on Nov 1. | `ROUTINE.md` |
| right after the push | `reel.yml` (push trigger on `queue/**`) renders each story's **Reel** video on GitHub's servers and stores it on branch `reels` + `state/reels.json`. `preview.yml` validates/renders the queue as an artifact. | `reel_job.py`, `make_reel.py` |
| every 10 min, all day | **The owner's Mac mini** runs `gh workflow run publish.yml` (launch agent). The workflow checks if a carousel or Reel is due, posts at most ONE, refreshes live Instagram numbers (`stats.py --quick`, at most every 25 min), rebuilds the dashboard, commits `state/ queue/ docs/`. | `publish.py`, `publish_reel.py`, `stats.py`, `dashboard.py` |
| 18:15 NY daily | One **backlog Reel** of an old post (see section 6). | `backfill_reels.py` |
| ongoing | Owner uses the **dashboard** to remove/replace/edit/reschedule anything, set counts, pause, manage music. | `control.py` |

Daily output with current settings: **3 carousel posts + 3 Reels from the same 3 stories** (+1 backlog Reel/day for a few days). Times
(New York base, each shifted randomly +-35 min per day): carousels 09:00 / 14:30 / 20:30 (slots 1,3,5 of `post_times`),
Reels 11:00 / 16:00 / 22:00 (slots 1,3,5 of `reel_times`), a story's Reel slot is rotated by one so its carousel and Reel are ~6+ h apart.
The owner is in Istanbul (UTC+3); US clocks changed Nov 1 2026 (NY now UTC-5).

## 2. Where things live
**Scripts (`scripts/`)**
- `publish.py` posts the next due carousel/Reel. Safety: `instagram_gate` reads Instagram's own recent posts (blocks duplicates, <45 min since any post, daily cap),
  `api_backoff` (30 min -> 4 h after Instagram refuses requests, `state/api_health.json`), random 0-4 min delay, 3 attempts. Reads `paused`. Pure poster: **no content checks here by owner's decision**.
- `publish_reel.py` posts a Reel (`REELS` container, `share_to_feed`), caption = post caption + hashtags + "Photos: credits" + music credit line; makes the Reel first if missing.
- `reel_job.py` / `make_reel.py` / `templates/reel.html` render Reels (Playwright frames -> ffmpeg), pick music (`pick_music`: rotates, never repeats within the last 5), refuse to render with a missing picture (retries throttled downloads).
- `render.py` + `templates/slide.html` render carousel slides (1080x1350 JPEG, Inter font, accent #FFD400, bg #0E0E10, photo layouts `split`/`full`, no slide counter).
- `validate.py` hard rules for a post (below). `check_images.py` downloads every picture, prints real size, warns small/duplicate, saves copies for the run to LOOK at.
- `plan_day.py` deals the daily run a RANDOM research plan (lane A/B per story, angle, which feeds/archives to start at, which picture archive to try first) and reseeds every run. The routine must start with it. Added Nov 1 because the run kept returning to one feed: 7 of the first 9 stories came from ScienceDaily.
- `find_images.py` Wikimedia Commons photo search that obeys rate limits (use it for Commons; own search loops got throttled on Nov 1). Wikimedia throttles even one-at-a-time requests (waits up to ~60 s are normal), so it is no longer the default archive: go to whoever owns the subject first (NASA/ESA, NOAA/USGS/FWS, Smithsonian, Library of Congress, Met, Internet Archive).
- `control.py` all dashboard actions (below). `backfill_reels.py` plans Reels for live posts without one. `stats.py` Instagram numbers (`--quick --min-age 25` or full daily read), `dashboard.py` builds `docs/index.html`, `watchdog.py` fails if nothing queued (emails only; owner never reads email).
- `stock.py` Unsplash lookup, re-enabled Nov 1 as a FALLBACK only: a slide with no real picture of the subject may use `{"image": {"search": "..."}}`, which the run resolves with `python3 scripts/stock.py queue/<date>` before validating. Credits must start with `Illustrative photo:`. Budget in config.json (`unsplash_max_requests_per_hour` 30 / `_per_day` 100).

**Workflows (`.github/workflows/`)**: `publish.yml` (driven by the Mac; its own cron is unreliable), `reel.yml`, `control.yml` (dashboard buttons), `preview.yml`, `stats.yml` (daily cron, unreliable; the quick refresh in publish.yml is what keeps numbers fresh), `watchdog.yml`.
A workflow started with the default `GITHUB_TOKEN` push does NOT trigger other workflows; use `gh workflow run` (workflow_dispatch IS allowed). The routine's pushes (Claude GitHub app) do trigger them.

**State (`state/`)**: `posted.json` (carousel bookkeeping: status posted/removed/deleted/failed, attempts, `post_now`, `post_at`, `media_id`), `reels.json` (Reel records: status pending/made/posted/failed/cancelled/expired, `post_at`, `backfill`, urls, music, attempts), `history.jsonl` (every story ever used; `validate.py` blocks reused sources/near-identical titles), `stats.json` + `report.md` (per-post Instagram numbers; the routine reads the report to learn), `account.json` (live followers + media_count + `fetched_at`), `followers.csv`, `control_log.json` (last 50 dashboard actions), `music_log.json`, `ping.json` (last Mac dispatch time), `api_health.json` (only while backing off), `unsplash_requests.json` (legacy).
**Other**: `assets/music/*.m4a` + `music.json` (6 Scott Buckley tracks, CC BY 4.0, credit lines per track), `docs/index.html` (GENERATED; never edit by hand; on merge conflicts take either side and rerun `scripts/dashboard.py --force`), `queue/<date>/<NN>/post.json` (NN = 01..; spares `s1`..; replaced posts parked as `NN-replaced`; `queue/demo/02` = an early live test post "demo-02" (Rubin dwarf planet) that is still on Instagram), `preview/` (git-ignored local renders), `.venv/` (Python 3.9 + playwright; Mac also has ffmpeg via Homebrew).
**Git branches**: `main` (everything), `media` (publisher force-pushes the post's slide images here so Instagram can fetch them), `reels` (orphan, force-pushed, newest 12 videos), `claude/tender-archimedes-*` (leftover working branches of routine runs; harmless, can be deleted).

## 3. Settings (`config.json`) and how to change them
| Setting | Meaning |
|---|---|
| `posts_per_day` / `active_slots` | carousels per day (0-5) and which of `post_times` they use |
| `reels_per_day` / `reel_active_slots` / `reel_times` | Reels per day (0-5) and their New York times |
| `reels_mode` | `same` (default): Reels reuse the carousel stories (no extra research). `different`: Reels get their own stories (`stories_per_day = posts + reels`; Reel-only stories have `slot: null`) |
| `stories_per_day` | what the research must write: `max(posts, reels)` in same mode. Set by `control.py`, not by hand |
| `spares_per_day` | extra finished posts the run prepares (`queue/<date>/s1`, `"spare": true`), used by the dashboard's Replace button. Cost extra Claude usage |
| `time_jitter_minutes`, `publish_random_delay_seconds` | natural-looking time variation |
| `max_posts_per_day` (= posts + reels + 2), `min_minutes_between_posts` 45, `ig_quota_stop` 25 | spam protection, checked against Instagram itself |
| `paused` | `true` stops all posting instantly |
| `backfill_reel_time`, `backfill_per_day` | old-post Reel plan (18:15 NY, 1/day) |
| `graph_host` `graph.facebook.com`, `graph_api_version` | Instagram API access (see section 5) |
| `brand`, `show_slide_counter` (false), `handle`, `account_name`, `timezone` | look and identity |
| `language` | language the stories are written in: `English (US)` |
| `audience` | who the account writes for: US, English-speaking. ROUTINE.md section 0 holds the rules (American spelling, US units, dollars, foreign context explained). The `timezone` above is the same decision: all slot times are New York times |
| `unsplash_max_requests_per_hour` / `_per_day` | budget for `stock.py` fallback photos (30/hour, 100/day) |
Prefer changing counts through the dashboard (it also recalculates the dependent settings). A change applies from the NEXT research run (today's queue is already written).

## 4. The dashboard (docs/index.html, GitHub Pages)
Tabs: **Overview** (alerts, live Instagram counters, "What's happening right now" in plain words + how-it-works, today's posts+Reels with quick buttons, reach and follower charts, results table, what's working, system), **Posts** (search, filters, each post: slides, caption, sources, results, its Reel with player, planned time), **Music** (listen/add by link/remove), **Control** (pause/resume, post and Reel counts, same/own stories, spares, run-now buttons, recent jobs, action log).
Buttons need the owner's fine-grained GitHub key (Actions read+write on this repo only) stored in that browser's localStorage; they start `control.yml` (`control.py` actions: `pause resume remove restore post_now reschedule replace edit_caption edit_slide posts_per_day reels_per_day reels_mode spares_per_day delete_instagram post_reel cancel_reel reschedule_reel add_music remove_music refresh_dashboard`), `reel.yml`, `publish.yml`, `stats.yml`, `preview.yml`. Results land in `state/control_log.json`. Edits (`edit_slide`, `edit_caption`) are refused only if they add a NEW `validate.py` error. Page lags up to ~10 min (GitHub Pages cache); layout is one column on phones and full-width two-column on desktops. Counters come from `state/account.json` (live from Instagram), "Posted today" from our schedule.
Build it: `python scripts/dashboard.py --force`. The publish workflow rebuilds it automatically.

## 5. Accounts and secrets (values NOT in the repo)
- Instagram `@unclefactss`, user id `17841415004854249`. Meta developer app `1110649915216695`, business portfolio "Unclefactss", Meta's "unified login": a **system-user token that never expires**, used on `graph.facebook.com`. Instagram-login tokens (`graph.instagram.com`) are not available to new apps. Content publishing limit 100 API posts/24 h (we cap far lower).
- GitHub Actions secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `UNSPLASH_ACCESS_KEY`. Never write tokens into files, commits or chat replies. **The Instagram token was pasted into the early chat history; it should be regenerated and the secret updated (open item).**
- GitHub account `amirpz04` (Claude GitHub app installed for it); `gh` is logged in on the Mac with scopes repo, workflow. Another GitHub account (`amirarsalan-pajouhi`) exists; do not use it.
- **Mac mini launch agent** `com.storyautopilot.ping` (`~/Library/LaunchAgents/com.storyautopilot.ping.plist`, every 600 s, runs `gh workflow run publish.yml -R amirpz04/story-autopilot --ref main`). Log `~/Library/Logs/story-autopilot-ping.log`. Stop: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.storyautopilot.ping.plist`. **The Mac must stay awake and online** (it is the clock). `pmset` showed `sleep 1` kept awake only by other processes (caffeinate/coreaudiod) on Nov 1; the owner should run `sudo pmset -a sleep 0 autorestart 1` (Claude cannot sudo; unverified whether done).

## 6. Reels
Each story can become a Reel: the same photos and text as the carousel, animated (camera moves, word-by-word text, fades), 1080x1920 30 fps, ~25-40 s, with a free song.
- **Layout is tuned for the owner's iPhone 13** (checked against his screenshot): Instagram covers the top ~11% (clock/Reels header), the right ~13% (like/comment/share/save column), and the bottom ~27% (caption, tab bar); iPhones also crop ~9% off each side of a 9:16 video. All Reel text stays inside the safe box (x 140-810, y ~460-1220 of 1920, auto-shrinks via `fitAll()`). No progress bars, no @handle on the video (Instagram shows the account). Photo credits go in the Reel caption. Do not move text out of the safe box.
- Music: `assets/music/music.json`; Instagram's own music library cannot be used through the API. Owner dislikes the old tracks (Kevin MacLeod, Satie) and likes the current six.
- **Backlog**: posts that went live before Reels existed (demo-02 Rubin, 2026-10-30-03 crocodile, 2026-10-30-01 Jupiter, 2026-10-31-03 salamanders, 2026-10-31-05 spiders) got Reels rendered and scheduled one per day at ~18:15 NY (Nov 1-5 NY dates; Istanbul ~02:00 next day). `find_due_reel` posts any Reel whose `post_at` arrived, in any queue folder. Cancel/move from the dashboard. A failed render keeps a backlog Reel pending (3 tries).
- The very first live Reel (ISS, 2026-10-31-01) was posted with the OLD layout (top bars, credit on video) and an old song; the owner has not decided whether to replace it (deleting is permanent: ask first).
- Hosting: Instagram fetches the mp4 from `raw.githubusercontent.com/.../reels` (works); the dashboard plays it via jsDelivr.

## 7. Rules enforced by `validate.py` (the run must satisfy them)
5-10 slides (story decides), slide text <= 40 words, cover headline <= 16 words, at least half the slides (min 3) with a real picture URL, never two text-only slides in a row, layout `split`/`full` only, caption 700-1500 chars, up to 5 hashtags, only in the `hashtags` field, every source has a URL, no reused source/near-duplicate title vs `history.jsonl` and the queue, `slot` in `active_slots` and/or `reel_slot` in `reel_active_slots` (at least one; spares have neither), no stock `search` images. Two whole-day rules (added Nov 1): the day must hold `stories_per_day` non-spare posts, and no two posts in a day may share a source website. The publisher itself does not validate (owner's decision).

## 8. Decisions the owner made (do not undo without asking)
- **The publisher only posts.** No rejecting, no failing runs, no emails. Quality checking belongs to the Claude research run (it runs `validate.py` + `check_images.py` and LOOKS at every picture). The owner never reads email: status goes on the dashboard.
- Posts are 5-10 slides, picture-rich, no slide counter, detailed caption; Reels are automatic (he refused "press Make Reel" flows); he chooses the counts (dropdowns 0-5 each). No AI-tool-spotlight posts. Real pictures of the real subject first; **Unsplash stock as a labelled fallback is allowed (owner, Nov 1) rather than losing a slide or a story**.
- Two story lanes: news (recent) and evergreen (any true, specific, surprising story about something humans built/did, needs 2 independent sources).
- Same-story Reels by default (cheaper); switchable. Owner asked about posting the carousel and Reel at the same time: advised no (keep >= ~6 h apart), untested.
- Tiny budget: everything free except the owner's Claude Pro plan; be careful with Claude usage.
- Instagram: official API only, no engagement bots, no password logins. Never publish or delete anything public without the owner's say unless it is the normal automatic flow.

## 9. Known gotchas
- GitHub's own scheduled workflows barely fire here; the Mac is the clock. Optional backup: cron-job.org calling `workflow_dispatch`.
- Carousels are published only from `queue/<today in New York>`; an unposted post from an earlier day never posts by itself (use the dashboard's Post now / Reschedule).
- Wikimedia throttles bursts (HTTP 429): always use `find_images.py`; thumbnails must use standard widths (the API's `thumburl` is right).
- Photos too small for a slot are dropped by the renderer; `check_images.py` warns. Reels refuse to render with a missing picture.
- macOS zsh: unquoted `$var` is not word-split, and `python3 -c` scripts in loops can misbehave; use scripts. Reddit/Instagram block automated browsing.
- Daylight saving shifts every posting time by an hour in Istanbul terms (NY schedule is fixed).
- Another Claude session (claude.ai chat, cloud, owner's phone) may edit this repo; on Nov 1 one built a partial backfill (replaced by section 6's design). Always `git pull`, check `git log` first.
- Early on, the Instagram API returned "API access blocked" (code 200) for about an hour with 0% usage; it cleared by itself, cause unknown.

## 10. Status (updated Nov 1 2026)
Live and posting. On Instagram: 6 carousels + 1 Reel (7 posts); 1 follower (probably the owner's other account); reach is tiny so far (new account). Dashboard counters verified equal to Instagram's.
**Nov 1: two runs in a row queued 1 story each** (09:15 automatic, 10:02 manual; both reported SUCCEEDED, the second used only 14 of its 25 minutes). Causes found: (a) ROUTINE.md section 9 explicitly allowed finishing with "even 1" story and promised the next run would fill the gap, so every run took that exit; (b) Wikimedia throttling (429s with 30-60 s waits) even through `find_images.py`; (c) source monoculture: 7 of the first 9 stories came from the ScienceDaily top feed, and lane B (evergreen) was never used at all. **All three addressed Nov 1**: `plan_day.py` (random lane/angle/source draw each run), ROUTINE sections 2, 3, 5 and 9 rewritten (hard floor on the count, "small is fine", at least one lane-B story a day, Wikimedia demoted to one archive among several), and `validate.py` now fails a short day or two posts from one website. Day stands at 2 of 3 (slot 3 still empty); **not yet observed whether the next run actually produces 3** — check this first.
**Open items**: (1) measure Claude usage of one daily run (owner: claude.ai/settings/usage before/after), (2) regenerate the Instagram token and update the `IG_ACCESS_TOKEN` secret, (3) owner to run the `pmset` command above, (4) decide about replacing the old-layout ISS Reel, (5) optional: change the Instagram display name from "Tech daddy", delete the old Rubin test post's "1/7" counter look, (6) after ~a week/15 posts compare what works (dashboard "What's working"), then consider more or fewer posts, and `reels_mode: different`, (7) watch the first backlog Reels and the first automatic daily Reels (not yet observed posting automatically except the ISS test).

## 11. Working with the owner
Not a developer; Istanbul, iPhone 13 and a Mac mini M4; often on his phone. Wants short plain answers, the "how" and not a verdict on his ideas, and results over explanations. He decides taste (looks, counts); you decide technical details. Confirm before anything public or irreversible. He gets frustrated by stale or wrong numbers, repeated asks, and being made to press buttons: automate, verify against live data before claiming something, and say plainly when something failed.
