# Uncle Facts (@unclefactss): autonomous Instagram story account

> **Daily research run** (cloud task "Daily stories"): ignore this file, follow `ROUTINE.md` only.
> **Maintenance sessions**: read this whole file, then `git pull` and `git log` before changing anything. The publisher bot,
> the daily run and other Claude sessions push to `main` all the time.

True, surprising stories (science, space, nature, animals, health, tech/AI, inventions, history, how things began) posted
fully automatically to Instagram **@unclefactss** as image carousels and animated Reels. Claude researches and writes;
scripts render, post and report. **Audience: United States, US English**; all times are New York times.
Repo (public): github.com/amirpz04/story-autopilot. Dashboard: https://amirpz04.github.io/story-autopilot/

## 1. A day
| When | What | Code |
|---|---|---|
| 09:15 UTC | **Research run** (cloud task id `trig_015p8XY87MCPiPaEgKXrXyxf`, environment "stories", prompt "follow ROUTINE.md exactly for today's run"): fixes anything that didn't go out, researches, verifies, picks real pictures, writes `queue/<NY date>/<NN>/post.json`, appends `state/history.jsonl`, runs `validate.py` + `check_images.py`, pushes. | `ROUTINE.md` |
| after that push | `reel.yml` renders each story's Reel (stored on branch `reels` + `state/reels.json`); `preview.yml` renders a preview artifact. | `reel_job.py`, `make_reel.py` |
| every 10 min | **Owner's Mac mini** runs `gh workflow run publish.yml`. It posts at most ONE due carousel or Reel, refreshes Instagram numbers (every 25 min), rebuilds the dashboard, commits `state/ queue/ docs/`. | `publish.py`, `publish_reel.py`, `stats.py`, `dashboard.py` |
| anytime | Owner uses the dashboard: remove, edit, reschedule, post now, counts, pause, music. | `control.py` |

**Current plan: 1 carousel + 2 Reels a day from 2 stories** (story 1 = carousel + Reel, story 2 = Reel only). NY times, each
shifted randomly up to +-35 min a day: carousel 09:00, Reels 16:00 and 22:00. A story's Reel slot is rotated so its carousel and
Reel are hours apart. Reduced from 3+3 on Nov 5 after Instagram spam blocks.

**Everything scheduled must go out.** A carousel or Reel of the last 2 days that missed its time is retried automatically
(`CATCH_UP_DAYS` in `publish.py`, max 3 tries, Instagram is checked first so nothing posts twice). Each miss shows on the dashboard
as an alert with a plain error. Content errors are fixed by the daily run (ROUTINE section 1b) or by you.

## 2. Files
**Scripts (`scripts/`)**
- `publish.py`: finds the due item and posts it. Safety: `instagram_gate` reads Instagram's own recent posts (no duplicates,
  45 min gap, daily cap); `api_backoff` waits 30 min -> 4 h after Instagram refuses (`state/api_health.json`); random 0-4 min delay.
  Never fails the run on an Instagram refusal (no emails). **No content checks here (owner's decision).**
- `publish_reel.py`: posts a Reel (`REELS`, `share_to_feed`); caption = post caption + hashtags + photo credits + music credit; re-renders an expired video first.
- `reel_job.py`, `make_reel.py`, `templates/reel.html`: Reel video (Playwright frames -> ffmpeg), music rotation (no repeat within 5).
- `render.py`, `templates/slide.html`: carousel slides (1080x1350 JPEG, Inter, accent #FFD400, bg #0E0E10, layouts `split`/`full`).
- `validate.py`: hard post rules (section 5). `check_images.py`: downloads every picture, real sizes, saves copies to look at.
- `plan_day.py`: random research plan per run (lane, subject, angle, where to look); `variety.py`: soft variety checks.
- `find_images.py`: rate-limited Wikimedia Commons search. `stock.py`: labelled Unsplash fallback photos (run by the research run and `preview.yml` only).
- `control.py`: every dashboard action. `backfill_reels.py`: Reels for old live posts that have none. `stats.py`: Instagram numbers + `state/report.md`. `dashboard.py`: builds `docs/index.html`.

**Workflows**: `publish.yml` (Mac-driven; GitHub's own cron barely fires), `reel.yml`, `control.yml` (dashboard buttons), `preview.yml`, `stats.yml`.
A push with the default `GITHUB_TOKEN` does not trigger other workflows; use `gh workflow run`. The research run's pushes do trigger them.

**State (`state/`)**: `posted.json` (carousels: status posted/removed/deleted/failed, attempts, error, `post_now`, `post_at`, `media_id`),
`reels.json` (Reels: pending/made/posted/failed/cancelled/expired, `post_at`, `backfill`, urls, music, attempts, error),
`history.jsonl` (every story used; blocks reuse), `stats.json` + `report.md` (per-post results; the run learns from the report),
`account.json` (followers, media_count: Instagram's count, which excludes Reels, like the profile counter), `followers.csv`,
`control_log.json`, `music_log.json`, `ping.json` (last Mac dispatch), `api_health.json`, `unsplash_requests.json`.

**Other**: `config.json` (section 3), `assets/music/` (6 Scott Buckley tracks, CC BY 4.0, credits in `music.json`),
`docs/index.html` (GENERATED: never hand-edit; on a merge conflict take either side and run `python scripts/dashboard.py --force`),
`queue/demo/02` (early test post "demo-02", still live), `.venv/` (Python 3.9 + Playwright; ffmpeg via Homebrew).
**Branches**: `main`; `media` (slide images for Instagram to fetch, force-pushed); `reels` (newest 12 videos, force-pushed).

## 3. Settings (`config.json`)
Change counts on the dashboard (it recalculates the dependent keys); changes apply from the NEXT research run.
| Key | Meaning |
|---|---|
| `posts_per_day` / `active_slots` / `post_times` | carousels a day (0-5), which slots, NY times |
| `reels_per_day` / `reel_active_slots` / `reel_times` | same for Reels |
| `reels_mode` | `same`: Reels reuse carousel stories. `different`: Reels get their own stories |
| `stories_per_day` | what the run writes (set by `control.py`) |
| `max_posts_per_day` (posts + reels + 2), `min_minutes_between_posts` 45, `ig_quota_stop` 25 | spam protection, checked against Instagram |
| `time_jitter_minutes`, `publish_random_delay_seconds` | natural timing |
| `paused` | `true` stops all posting |
| `backfill_reel_time`, `backfill_per_day` | Reels for old posts (18:15 NY, 1/day) |
| `graph_host` (`graph.facebook.com`), `graph_api_version` | Instagram API |
| `brand`, `handle`, `account_name`, `timezone`, `language`, `audience`, `show_slide_counter` (false) | identity and look |
| `variety_rules_from` | first date the variety rules apply |
| `unsplash_max_requests_per_hour` / `_per_day` | stock photo budget (30 / 100) |

## 4. Dashboard
Dark "bento" design (owner's reference, Nov 5): mono font (JetBrains Mono), slate-blue accent #5b6c92, light tile #b9b8b0.
Uses only data already in the repo (no extra Instagram requests). Top ticker (followers, live count, 7-day reach/views, today, next, status).
**Overview**: alerts, Today, Next up (countdown, post now), chart by day posted (7D/30D/All, all/reels/posts, reach/views/interactions),
followers, average reach Reel vs carousel (24h+ old), Delivered ring (7 days, due vs went out), engagement, latest 9 on Instagram,
top post, system (Mac, Instagram wait, numbers age, today's stories, posting), what's working (from `groups`), results table.
**Posts**: search, sort, filters (upcoming/live/reels/problems/removed), detail page with all actions. **Control**: GitHub key, pause,
counts, run-now, page options (time zone, default range/metric, 5-min auto reload, gray/color pictures; stored in localStorage
`uf_prefs`), recent jobs, music, action log. Buttons use the owner's GitHub key in that browser and start `control.yml` (actions:
`pause resume remove restore post_now reschedule edit_caption edit_slide posts_per_day reels_per_day reels_mode delete_instagram
post_reel cancel_reel reschedule_reel add_music remove_music refresh_dashboard`). Results go to `state/control_log.json`.
Template `templates/dashboard.html`, data `scripts/dashboard.py`. GitHub Pages lags up to ~10 min.

## 5. Post rules (`validate.py`)
5-10 slides; slide text <= 40 words; cover headline <= 16 words; at least half the slides (min 3) with a real picture; never two
text-only slides in a row; layouts `split`/`full`; caption 700-1500 chars; up to 5 hashtags, only in `hashtags`; every source has
a URL; no reused source or near-duplicate title; `slot` in `active_slots` and/or `reel_slot` in `reel_active_slots`. Per day:
exactly `stories_per_day` stories; soft variety (no shared source organization, subject or opening words, unless the post carries
a `variety_exception` reason).

## 6. Reels
Same photos and text as the carousel, animated, 1080x1920, 30 fps, ~25-40 s, with music.
- **Safe box for the owner's iPhone 13**: all text inside x 140-810, y ~460-1220 (Instagram covers the top 11%, right 13%,
  bottom 27%; iPhones crop ~9% per side). No progress bars, no @handle on the video; photo credits go in the caption. Do not move text out of the box.
- Music: Instagram's own library is not available through the API. Owner likes the current six tracks, dislikes Kevin MacLeod and Satie.
- Hosting: Instagram fetches the mp4 from `raw.githubusercontent.com` (branch `reels`); the dashboard plays it via jsDelivr.

## 7. Accounts and secrets (never in files, commits or chat)
- Instagram user id `17841415004854249`; Meta app `1110649915216695`, business portfolio "Unclefactss"; system-user token that never
  expires, on `graph.facebook.com`. Publishing limit 100 API posts/24 h (we post 3). Instagram's spam filter (error code 4 / 2207051,
  "action is blocked") is the real limit for a new account; sometimes the post still goes live.
- GitHub secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `UNSPLASH_ACCESS_KEY`.
- GitHub account `amirpz04` (`gh` logged in on the Mac). Do not use the other account `amirarsalan-pajouhi`.
- **Mac launch agent** `com.storyautopilot.ping` (`~/Library/LaunchAgents/com.storyautopilot.ping.plist`, every 600 s; log
  `~/Library/Logs/story-autopilot-ping.log`). The Mac is the clock: it must stay awake and online.

## 8. Owner decisions (do not undo without asking)
- **The publisher only posts**: no content checks, no failing runs, no emails. Quality belongs to the research run. Status goes on the dashboard (he never reads email).
- Picture-rich 5-10 slide posts, no slide counter, detailed caption. Real pictures of the subject first; labelled Unsplash fallback allowed.
- Reels are automatic. He picks the counts. No spare posts (removed Nov 5). No AI-tool-spotlight posts.
- Two lanes: news and evergreen (evergreen needs 2 independent sources).
- Keep a story's carousel and Reel hours apart.
- Tiny budget: only his Claude Pro plan costs money; keep Claude usage low.
- Official Instagram API only; no bots, no password logins. Never publish or delete anything public outside the normal flow without asking.

## 9. Gotchas
- Wikimedia throttles (HTTP 429): use `find_images.py`, standard thumbnail widths; prefer the subject's own archive (NASA, NOAA, Smithsonian, LoC, ...).
- Photos too small are dropped by the renderer; Reels refuse to render with a missing picture.
- macOS zsh: unquoted `$var` is not word-split; put multi-line Python in scripts, not `python3 -c` loops.
- Reddit and Instagram block automated browsing.

## 10. Open items
1. Regenerate the Instagram token (it was pasted in an early chat) and update `IG_ACCESS_TOKEN`.
2. Owner to run `sudo pmset -a sleep 0 autorestart 1` on the Mac (unverified).
3. Measure Claude usage of one daily run.
4. Old-layout ISS Reel (2026-10-31-01): replace or keep? Deleting is permanent; ask.
5. After ~2 weeks on 1+2 with no spam blocks, review results ("What's working") before raising counts.

## 11. Working with the owner
Not a developer; Istanbul (UTC+3), iPhone 13, Mac mini M4, often on his phone. Wants short plain answers and results, not
explanations or verdicts on his ideas. He decides taste (looks, counts); you decide technical details. Confirm before anything
public or irreversible. Automate rather than asking him to press buttons; verify against live data before stating numbers; say
plainly when something failed.
