# Uncle Facts (@unclefactss): autonomous Instagram story account

> If you are the **daily research run** (a cloud routine), ignore this file and follow `ROUTINE.md` only.
> This file is for maintenance sessions where the owner asks for changes or fixes.

Posts 3 carousels a day (tech, science, space, nature, health, inventions, major news) about real
stories found on the open web. Fully automatic: Claude researches and writes, scripts render and post.
Public repo: github.com/amirpz04/story-autopilot. Dashboard: https://amirpz04.github.io/story-autopilot/

## How it runs (end to end)
1. **Daily Claude routine** ("Daily stories", claude.ai/code scheduled task, id `trig_015p8XY87MCPiPaEgKXrXyxf`,
   cloud environment "stories" with full network access, 12:15 Istanbul = 09:15 UTC). Prompt: "follow ROUTINE.md
   exactly for today's run". It researches, verifies, finds pictures, writes `queue/<New York date>/<slot>/post.json`,
   updates `state/history.jsonl`, pushes to `main`. Manage with the `RemoteTrigger` tool (list/get/update/run/list_runs/get_run_log).
2. **Mac mini launch agent** `com.storyautopilot.ping` (`~/Library/LaunchAgents/`) runs every 10 min:
   `gh workflow run publish.yml`. Needed because GitHub's own cron barely fires on this repo. The Mac must stay
   awake and online (owner must run `sudo pmset -a sleep 0 autorestart 1`; Claude cannot sudo).
   Log: `~/Library/Logs/story-autopilot-ping.log`. Stop: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.storyautopilot.ping.plist`.
3. **Publish workflow** (`.github/workflows/publish.yml`): `scripts/stock.py` (legacy Unsplash lookup), then
   `scripts/publish.py` posts the next due post (renders slides with Playwright, uploads images to the repo's `media`
   branch, publishes through the Instagram API), then `scripts/dashboard.py`, then commits `state/` `queue/` `docs/`.
4. **Stats workflow** daily (`scripts/stats.py`) writes `state/stats.json`, `state/report.md`, `state/followers.csv`.
   The routine reads `state/report.md` to learn what works. **Watchdog workflow** fails if nothing is queued by morning.
5. **Preview workflow** renders any pushed queue to an artifact. **Dashboard / control panel** = `docs/index.html`
   (GitHub Pages; tabs Overview, Posts, Control). Its buttons start the **Control workflow** (`control.yml` ->
   `scripts/control.py`: pause, resume, remove, restore, post_now, posts_per_day, delete_instagram, refresh_dashboard),
   using a fine-grained GitHub key (Actions read/write, this repo only) that the owner pastes into the page; it lives
   only in their browser's localStorage. Actions are logged in `state/control_log.json`. `delete_instagram` uses
   Meta's DELETE media endpoint and was untested at the time of writing.

## Where to change things
| Want to change | Where |
|---|---|
| posts per day / which posting times | `config.json`: `posts_per_day`, `active_slots` (of `post_times`), `post_times`, `time_jitter_minutes` |
| stop / resume all posting instantly | `config.json`: `"paused": true/false` |
| spam protection | `config.json`: `max_posts_per_day`, `min_minutes_between_posts`, `ig_quota_stop` (checked against Instagram itself in `publish.py: instagram_gate`) |
| Unsplash limits | `config.json`: `unsplash_max_requests_per_hour/day` (legacy; the routine no longer uses stock searches) |
| what stories, tone, verification, captions, picture rules | `ROUTINE.md` (the routine's full instructions) |
| hard rules on a post (slides 5-10, pictures, text length, caption 700-1500 chars, duplicates) | `scripts/validate.py` |
| look of slides / brand colours / counter | `templates/slide.html`, `config.json` `brand`, `show_slide_counter` |
| routine time, model, prompt | the scheduled task (`RemoteTrigger update`, or claude.ai/code) |
| dashboard | `templates/dashboard.html` + `scripts/dashboard.py` |

After any change: run `python scripts/validate.py queue/<date>` and `python scripts/render.py` locally (venv at `.venv/`),
commit, push to `main` (goes live immediately). For publisher changes set `paused: true` first.

## Accounts and secrets (values are NOT in the repo)
- Instagram `@unclefactss`, user id `17841415004854249`, Creator account. Meta developer app `1110649915216695` uses
  Meta's new "unified login": a **system-user token that never expires**, used on `graph.facebook.com`
  (`config.json` `graph_host`). Business portfolio "Unclefactss". Instagram login tokens (`graph.instagram.com`) are not available to new apps.
- GitHub Actions secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `UNSPLASH_ACCESS_KEY`. Never write tokens into files or commits.
- The Instagram token was pasted into an early chat; regenerate it (Meta app > Instagram API setup > Generate token, or system user) and update the secret when convenient.
- GitHub account `amirpz04` (the Claude GitHub app is installed for it). `gh` is logged in on the Mac.

## Decisions the owner made (and why), do not undo without asking
- **The publisher only posts.** No content checks, no failure emails that reject posts. All quality checking belongs to the Claude routine (it must run `scripts/check_images.py`, open every saved picture with Read, and fix problems). The owner never reads email: status goes on the dashboard.
- **5-10 slides per post, the story decides** (simple 5-6, rich up to 10; never pad), **picture-rich** (at least half the slides, min 3, have a real picture; never two text-only slides in a row; `layout: full` photo slides). Owner disliked 8 slides and walls of black text slides. No slide counter ("1/7") on images. Detailed caption (~900-1300 chars) under each post.
- **No AI tool spotlight posts** (switched off for now). Real pictures only; stock `search` images are disabled.
- Budget is tiny: everything free except the owner's Claude Pro plan. Be careful with Claude usage (the routine runs Opus 5.5; if usage is high switch to Sonnet 5.5 or 2 posts/day).
- Instagram rules: official API only, no engagement bots, no unofficial login. Post times shift randomly by +-35 min per day.

- **Two lanes (Oct 31 2026):** A = news (tech/science/space/nature/animals/health/AI), B = **evergreen** (any true, interesting story about something humans built or did, any age: how technologies work, company and founder origin stories, books, languages, machines, history; no topic limit, but needs 2 independent sources and a specific surprising hook). Posts are tagged `lane` so the dashboard can compare them.

## Reel system (automatic since Nov 1 2026)
- `scripts/make_reel.py <post_dir> [out.mp4] [music.ogg | auto]` turns a queued post into an animated vertical video using the same photos and text
  (`templates/reel.html`: camera moves on photos, word-by-word text, fades, progress bars). Renders frames in Playwright then encodes with ffmpeg (~1 min, free).
- Music: `assets/music/*.m4a` (AAC so phones can play them) with `music.json` (title, caption credit line, license, source). Managed from the dashboard's **Music** tab (listen, add by direct link, remove) via control actions `add_music` / `remove_music`. `auto` rotates
  so a song never repeats within the last 5 (`state/music_log.json`). Instagram's own music library cannot be used through the API (Meta docs).
- **Counts are owner-controlled:** `config.json` `posts_per_day` (carousels, 0-5) and `reels_per_day` (0-5), set from the dashboard Control tab (`posts_per_day` / `reels_per_day` actions).
  `stories_per_day = max(both)`; each story in post.json has `slot` (carousel slot or null) and `reel_slot` (Reel slot or null; times come from `reel_times`,
  `reel_active_slots`). Default (set Nov 1 2026) 3 posts + 3 Reels from the same 3 stories (no extra Claude usage); a story's Reel slot is rotated by one so its carousel and Reel are about 6+ h apart.
- **Flow:** the routine pushes the queue -> `reel.yml` (push trigger) renders each needed Reel (`reel_job.py`, stored on branch `reels`, `state/reels.json`) ->
  `publish.py` posts a Reel at its `reel_slot` time (`publish_reel.publish_due_reel`, makes it on the spot if missing; 3 attempts) with the same Instagram safety gate
  (45 min gap between ANY posts, daily cap = posts + reels + 1). Editing slides or replacing a post re-makes its Reel. Reels stats are tagged `kind: reel`.
- **Reel layout is tuned for an iPhone 13** (owner's phone): all Reel text stays inside a safe box (x 140-840, y about 460-1220 of the 1080x1920 frame) so it clears the
  notch/clock and Reels header (top ~12%), the right-hand like/comment/share buttons (right ~13%), and the caption + comment bar (bottom ~28%); iPhone screens crop the
  sides of a 9:16 video by about 9% each. No progress bars or @handle on Reels (Instagram already shows the account). Long text auto-shrinks (`fitAll()` in
  `templates/reel.html`). Photo credits go into the Reel caption ("Photos: ..."), not on the video. Do not move text outside the safe box.
- **`reels_mode`** (config; control action `reels_mode`): `same` = Reels reuse the carousel stories (default, no extra research); `different` = Reels get their own stories (stories_per_day = posts + reels, Reel-only stories have `slot: null`). Owner asked whether followers seeing the same story twice is a problem; `same` is the default because at 0 followers nobody sees both.
- The owner's "Make Reel" / "Post this Reel" buttons still exist for manual cases but are not needed.
- First live Reel: not yet published as of writing (the automatic flow is untested live).

## Control panel v2 (Nov 1 2026)
Dashboard tabs: Overview (alerts, tiles, today's posts with quick buttons, reach chart, followers), Posts (search, filters, per-post page with slides, caption, sources,
results, Reel), Control. Buttons start workflows with a GitHub key in the browser: `control.yml` (`scripts/control.py`: remove/restore any non-live post, post_now,
reschedule (`post_at` in state/posted.json), replace (swap in a spare; old post parked in folder `NN-replaced`), edit_caption, edit_slide `ID#N`, posts_per_day,
spares_per_day, delete_instagram, post_reel) and `reel.yml` (`scripts/reel_job.py`: renders a Reel on GitHub, stores it on the orphan `reels` branch, newest 12 kept,
records `state/reels.json`). Edits are refused only if they add a new `validate.py` error.
**Spares:** config `spares_per_day` (default 1): the research run writes finished posts to `queue/<date>/s1` with `"spare": true, "slot": null`; the publisher never posts
spares; `replace` moves one into a scheduled slot. They cost extra Claude usage.
**Reel hosting (tested Oct 31 with real containers, nothing published):** Instagram fetched and processed an mp4 from both raw.githubusercontent.com and jsDelivr
(`cdn.jsdelivr.net/gh/<repo>@<sha>/<file>`, video/mp4, 20 MB limit, used for dashboard playback). `post_reel` (REELS container, share_to_feed) is written but has not
yet published a live Reel. Reels are not yet automatic: owner presses Make Reel and Post this Reel.

## Request safety (audited Oct 31 2026)
Only ~2 of ~130 daily Publish runs touch Instagram (only when a post is due). If Instagram refuses a request, `publish.py` backs off (30 min, then 1 h, 2 h, up to 4 h;
`state/api_health.json`) and the dashboard shows it. `stats.py` skips posts older than 30 days. A temporary "API access blocked" (code 200) from Meta appeared once
for about an hour on Oct 31 and cleared on its own; the cause is unknown.

## Known gotchas
- GitHub's scheduled workflows are unreliable here (2 runs in 18 h); the Mac ping is the real clock. Optional backup: cron-job.org calling `workflow_dispatch`.
- Posts are published from `queue/<today in New York>`; a folder from an earlier date never posts.
- Photos too small for their slot are silently dropped by the renderer (`check_images.py` warns about it).
- `state/posted.json` is bookkeeping, but real safety comes from Instagram's own recent posts (`instagram_gate`).
- Reddit and Instagram block automated browsing; use official APIs and RSS feeds.

## Status when this file was written (Oct 31 2026)
Live and posting. First routine run with the new picture-checking rules is Nov 1 (12:15 Istanbul): review its posts.
Still unmeasured: how much Claude usage one daily run takes (owner to check claude.ai/settings/usage before and after).
Owner is in Istanbul (UTC+3), audience posting times are New York based; US clocks change Nov 1.

## Working with the owner
Not a developer. Wants short plain answers, the "how" and not a verdict on his ideas, and results over explanations.
He decides taste (looks, post count); you decide technical details. Confirm before anything public or irreversible.
