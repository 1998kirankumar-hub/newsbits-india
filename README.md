# NewsBits India

A self-updating news site: short bullet-point headlines pulled from public
RSS feeds (Indian + world news), auto-refreshed on a schedule, ready to
publish for free on GitHub Pages and monetize with Google AdSense.

## What's in this folder

| File | Purpose |
|---|---|
| `index.html` | The site itself — category tabs, bullet-point headline list, ad slots |
| `style.css` | Styling (light/dark mode) |
| `script.js` | Loads `news.json` and renders it, handles tabs + dark mode |
| `news.json` | The current headlines. Gets overwritten automatically. |
| `fetch_news.py` | Pulls headlines from RSS feeds and rewrites `news.json` |
| `.github/workflows/update-news.yml` | GitHub Action that runs `fetch_news.py` every 30 minutes |
| `about.html` / `privacy.html` | Required-ish pages for ad network approval — edit before publishing |

No server, database, or paid hosting required. GitHub Pages serves the
static files, and a free GitHub Action keeps `news.json` fresh.

---

## 1. Publish the site (GitHub Pages)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a new repository** — e.g. `newsbits-india`. Public, no README/gitignore needed (you already have these files).
3. **Upload these files** to the repo. Easiest way if you don't use git:
   - On the repo page, click **Add file → Upload files**, drag in everything from this folder (including the `.github` folder — GitHub will preserve its path), and commit.
   - Or, if you're comfortable with git:
     ```
     git init
     git add .
     git commit -m "Initial site"
     git branch -M main
     git remote add origin https://github.com/YOUR_USERNAME/newsbits-india.git
     git push -u origin main
     ```
4. **Enable the Action to push commits:** Repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save. (Without this, the auto-update commit will fail.)
5. **Run the feed fetcher once manually** so the site has real content immediately: Repo → **Actions** tab → **Update News Feed** workflow → **Run workflow**. Wait ~30 seconds, then check that `news.json` in the repo now has real headlines.
6. **Turn on Pages:** Repo → **Settings → Pages** → under "Build and deployment", set **Source: Deploy from a branch**, **Branch: main**, folder **/ (root)** → Save.
7. GitHub will give you a URL like `https://YOUR_USERNAME.github.io/newsbits-india/`. That's your live site. It can take a minute or two to go live the first time.

From now on, the GitHub Action fetches new headlines every 30 minutes automatically and commits the update — no server or manual work needed. You can change the schedule by editing the `cron` line in `.github/workflows/update-news.yml` (it's currently set conservatively; you could go as frequent as every 5–10 minutes if you want).

### Using your own domain (optional)
Once live on GitHub Pages, you can point a custom domain (e.g. `newsbitsindia.com`, bought from any registrar) at it — Settings → Pages → Custom domain. A custom domain isn't required to apply for AdSense, but it looks more professional and is easier to remember.

---

## 2. Before applying for ads: fill in the real details

Ad networks review sites for genuine content and transparency. Before applying:

- **Edit `about.html`** — replace the placeholder with a real paragraph about who runs the site and why.
- **Edit `privacy.html`** — replace `youremail@example.com` with a real contact email, and review the text so it accurately describes what the site does.
- **Edit the footer `mailto:` link in `index.html`** to your real email.
- Let the site run for at least a few days/weeks with real, frequently-updating content — most ad networks want to see an established, active site rather than one submitted the same day it's created.

## 3. Apply for Google AdSense

1. Go to **google.com/adsense** and sign up with the same Google account you want payments sent to.
2. Add your site's URL (your GitHub Pages URL or custom domain).
3. AdSense will give you a snippet like:
   ```html
   <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-XXXXXXXXXXXXXXXX" crossorigin="anonymous"></script>
   ```
   Paste it into `index.html` where the comment says `GOOGLE ADSENSE` (just above `</head>`), then re-upload/commit the file.
4. AdSense also asks you to create an **`ads.txt`** file at your site root containing a line like:
   ```
   google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0
   ```
   Create a file named `ads.txt` in this same folder with that exact line (AdSense shows you the exact text to use) and publish it the same way as the other files.
5. Google reviews the site — this typically takes anywhere from a few days to a few weeks. You'll get an email when it's approved or if changes are requested.
6. Once approved, replace the three placeholder `<div class="ad-slot">` boxes in `index.html` (top banner, in-feed, footer) with the actual `<ins class="adsbygoogle">` ad unit code AdSense gives you for each placement, or turn on **Auto ads** in the AdSense dashboard and skip manual placement entirely.

**Realistic expectations:** AdSense pays based on traffic and clicks — a brand-new site earns close to nothing until it has a real, returning audience. Growing traffic (via search, social sharing, or a niche people search for) matters more than the ad placement itself. If AdSense doesn't approve you, alternatives include Media.net, Ezoic, or affiliate links relevant to your content.

---

## 4. Turning on AI-rewritten summaries (free)

By default each summary is the publisher's own RSS snippet, truncated. To
have summaries rewritten in original wording instead (longer, in NewsBits'
own voice, not copied text) using **Google's Gemini API — no credit card
required**:

1. Go to **aistudio.google.com**, sign in with a Google account, and create
   an API key ("Get API key"). No payment details needed.
2. In your repo: **Settings → Secrets and variables → Actions → New
   repository secret**. Name it `GEMINI_API_KEY`, paste the key value, save.
3. Trigger the **Update News Feed** workflow once (Actions tab → Run
   workflow) — from then on, every new article gets rewritten automatically.

Gemini's free tier has no per-token cost, just rate limits. A
`summary_cache.json` file (committed alongside `news.json`) makes sure a
given article is only ever rewritten once, so re-runs every 30 minutes
don't waste calls on articles already seen. If the secret isn't set, the
site just falls back to the plain publisher snippet — nothing breaks.

**Heads up on the free tier's real limits:** Google documents fairly
generous free-tier numbers, but the actual limit granted to a given
account can be lower — check yours at
[aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit).
`fetch_news.py` defaults to a conservative 15 rewrites/day (`DAILY_AI_CALL_LIMIT`)
tracked in a committed `ai_usage.json` file, which resets at midnight
Pacific time. This means summaries get rewritten gradually — roughly 15
articles a day — rather than all at once, until every current headline
has been rewritten and cached. If your account's dashboard shows higher
limits, raise `DAILY_AI_CALL_LIMIT` in `fetch_news.py` accordingly.

(This site originally used Groq's free API instead. Groq turned out to
block requests from datacenter/CI IPs — including GitHub Actions runners —
as an anti-abuse measure, so every rewrite call failed with a 403 even
though the key itself was valid. Gemini doesn't have that restriction.)

---

## 5. Customizing the news sources

Open `fetch_news.py` and edit the `FEEDS` dictionary — it's a plain list of
`(source name, RSS feed URL)` pairs grouped by category. Add, remove, or
swap any standard RSS/Atom feed URL. A single broken feed won't break the
site; `fetch_news.py` skips failures and logs a warning.

To test changes locally before pushing: `python3 fetch_news.py` (requires
only the Python standard library — no installs needed) and open
`index.html` in a browser, or run `python3 -m http.server` in this folder
and visit `http://localhost:8000`.
