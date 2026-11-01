# Uncle Facts: an autonomous Instagram story account

Every day Claude researches true stories on the open web, fact-checks them, picks real photos, and writes finished Instagram
**carousel posts and animated Reels**. Scripts render them, post them at natural times through the day, collect Instagram's numbers,
and show everything on a dashboard where you can change anything before it goes out.
Cost: **$0** on top of a Claude Pro plan (GitHub Actions, GitHub Pages and the Instagram API are free).

Live account: **@unclefactss** · Dashboard: **https://amirpz04.github.io/story-autopilot/**
(New session? Read `CLAUDE.md` first: it is the full technical handover.)

## How it works
```
 12:15 Istanbul  Claude research run (cloud) ──► queue/<date>/NN/post.json  (3 stories, + spares)
       │                                              │ push
       │                                              ▼
       │                                   GitHub: render Reels (reel.yml), preview
       ▼
 every 10 min   Mac mini ──► GitHub "Publish" ──► posts whatever is due (one thing per check)
                                 │                  ├─ carousel: slides rendered, uploaded, posted via Instagram API
                                 │                  └─ Reel: animated video + free music, posted via Instagram API
                                 ├─► refreshes live Instagram numbers and the dashboard
                                 ▼
                      Dashboard (GitHub Pages): status, posts, music, controls
```
Defaults: **3 carousel posts + 3 Reels a day** from the same 3 stories (change 0-5 of each on the dashboard's Control tab),
posting times shifted a few minutes every day, nothing within 45 minutes of anything else.

## What is where
| Path | What it is |
|---|---|
| `CLAUDE.md` | Full handover for Claude sessions: architecture, settings, decisions, gotchas, status, open items |
| `ROUTINE.md` | The daily research run's complete instructions (what to find, how to verify, pictures, writing, slots) |
| `config.json` | All settings (counts, times, caps, pause switch, brand) |
| `scripts/` | `publish.py`, `publish_reel.py` (posting) · `render.py`, `make_reel.py`, `reel_job.py` (slides/videos) · `validate.py`, `check_images.py`, `find_images.py` (quality, photos) · `control.py` (dashboard actions) · `stats.py`, `dashboard.py`, `backfill_reels.py`, `watchdog.py`, `stock.py` |
| `templates/` | `slide.html`, `reel.html`, `dashboard.html` and the bundled font |
| `queue/<date>/<NN>/post.json` | One story each (slides, caption, sources, slots); `queue/demo/` holds an early live test post |
| `state/` | Everything the system remembers: posted/Reel records, history of used stories, Instagram stats, live account totals, action log |
| `assets/music/` | Reel songs (`music.json` has licenses and credit lines) |
| `docs/index.html` | The generated dashboard (never edit by hand) |
| `.github/workflows/` | `publish`, `reel`, `control`, `preview`, `stats`, `watchdog` |

## Running it day to day
Open the dashboard. **Overview** tells you in plain words what is happening and what is next; **Posts** lets you open any post (and its Reel) and remove, replace with a spare, edit text, reschedule, post now, or delete;
**Music** manages Reel songs; **Control** pauses posting and sets how many posts/Reels per day. Buttons need a one-time GitHub key pasted into that browser (the Control tab explains how).
Look at the posts before they go out for the first weeks; the numbers on the page come straight from Instagram.

## Setting it up from scratch
1. **Instagram**: switch the account to a Creator/Business (professional) account. In a Meta developer app (use case "Manage messaging & content on Instagram", Meta's *unified login*) create a business portfolio, a **system user** with access to the Instagram account and the app, and generate a never-expiring token with `instagram_basic` and `instagram_content_publish`. (Meta's old Instagram-login token screen is not available to new apps.)
2. **GitHub**: a public repo (public so Instagram can fetch images/videos and Actions stay free). Secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `UNSPLASH_ACCESS_KEY`. Settings → Actions → General → "Read and write permissions". Settings → Pages → deploy from `main` `/docs`.
3. **Claude research run**: at claude.ai/code connect GitHub, create a scheduled task on this repo with a cloud environment that has full network access, prompt `follow ROUTINE.md exactly for today's run`, daily at 12:15 Istanbul (09:15 UTC). Make sure it may push to `main`.
4. **The clock**: GitHub's own timer is unreliable. On an always-on Mac, install a launch agent that runs `gh workflow run publish.yml -R <owner>/<repo> --ref main` every 10 minutes (see `CLAUDE.md` section 5), and set the Mac to never sleep.
5. **Dashboard buttons**: create a fine-grained GitHub token (this repo only, Actions read+write) and paste it on the dashboard's Control tab.

## Limits and safety
Instagram allows 100 API posts per 24 h; this system caps itself far lower and checks Instagram's own record before every post (no duplicates, no bursts).
If Instagram refuses requests the poster backs off for 30 min, then 1 h, 2 h, up to 4 h. Everything can be stopped instantly with `"paused": true` in `config.json` or the dashboard's Pause button.
Only music and photos with free licenses are used, and the required credit lines are added to captions automatically.
