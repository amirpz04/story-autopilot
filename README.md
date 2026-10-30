# Story account autopilot

Finds stories on the web every morning, fact-checks them, writes Instagram
carousel posts, and publishes them at fixed times through the day. Runs on your
Claude Pro plan plus free GitHub services.

```
5:00   Claude routine (cloud, your Pro plan)  -> researches, writes queue/<date>/NN/post.json, pushes
push   GitHub Actions "Preview"               -> renders slides you can download and check
every 30 min  GitHub Actions "Publish"         -> posts the next due post to Instagram
```

| File | What it is |
|---|---|
| `ROUTINE.md` | The editor's instructions Claude follows every run (what to look for, how to verify, how to write) |
| `config.json` | Account name, handle, timezone, posts per day, posting times, colors |
| `scripts/render.py` | Turns a post into 1080×1350 slides |
| `scripts/validate.py` | Rejects broken posts before they can go out |
| `scripts/publish.py` | Posts to Instagram through the official API |
| `state/history.jsonl` | Every story ever used, so nothing repeats |
| `state/posted.json` | What has been published |

Preview a day locally: `.venv/bin/python scripts/render.py queue/2026-10-30` (slides land in `preview/`).

## Setup

### 1. Instagram (Meta's "unified login" setup)
New Meta apps use a system-user token that never expires, so no token renewal is needed. In the Meta app: **Use cases → Manage messaging & content on Instagram → Customize → API setup with unified login → Create new configuration** (needs a free business portfolio), then create a **system user** in Business Settings, assign it your Instagram account and the app, and generate a token with `instagram_basic` and `instagram_content_publish`. Save it as `IG_ACCESS_TOKEN` and your Instagram account ID as `IG_USER_ID`. (The older steps below describe the legacy Instagram-login screen.)

#### Legacy steps
1. In the Instagram app: **Settings → Account type and tools → Switch to professional account** (Creator or Business).
2. Go to [developers.facebook.com](https://developers.facebook.com), log in, **Create app**, and pick the use case **"Manage messaging & content on Instagram"**.
3. In the app, open **Instagram → API setup with Instagram login**. Under **Generate access tokens**, click **Add account**, log in with your Instagram account and approve.
4. Click **Generate token**. Copy the **token** and the **Instagram user ID** shown next to the account. You don't need app review: your own account can publish while the app is in development mode.

### 2. GitHub (about 10 minutes)
1. Create a free account at [github.com](https://github.com) and a new **public** repository (public is needed so Instagram can download the images, and it makes GitHub Actions free).
2. Push this folder to it.
3. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `IG_USER_ID`: the Instagram user ID
   - `IG_ACCESS_TOKEN`: the token
   - `UNSPLASH_ACCESS_KEY`: the **Access Key** of a free app at [unsplash.com/oauth/applications](https://unsplash.com/oauth/applications). Used for stock photos when a story has no real photo; the system never makes more than 30 Unsplash requests per hour.
4. **Settings → Actions → General → Workflow permissions →** "Read and write permissions".

### 3. Claude routine (about 5 minutes)
1. Go to [claude.ai/code](https://claude.ai/code) and connect GitHub.
2. Create a **routine** on this repository, scheduled daily at 05:00 in your posting timezone, with the prompt:
   `Follow ROUTINE.md exactly for today's run.`
3. Allow the routine to push to `main` (in the routine's repository settings).
4. Optional: a second routine at 13:00 with the prompt
   `Follow ROUTINE.md. This is the midday refresh: only replace posts that haven't been published yet, and only with clearly stronger, newer stories.`

### 4. Test
1. Run the routine once manually and check the **Preview** workflow's slides.
2. In the **Actions** tab, run **Publish** manually to confirm a post goes out.
