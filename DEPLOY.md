# Deploying the dashboard to a live URL (free)

The app runs **without a database** in the cloud; it automatically falls back to the committed
`data/films_enriched.csv` (5,659 films) and the cached `data/posters.json`, so there's
nothing to provision. Host it on **Render**'s free tier.

Files that make this work (already in the repo): `Procfile`, `.python-version`,
`gunicorn` in `requirements.txt`, and the committed CSV + poster cache.

## One-time setup (do it the night before, to leave time to test)

1. **Push the repo to GitHub** (Render deploys from GitHub):
   ```
   git push origin master
   ```
2. Go to **https://render.com** → sign up / log in (free; sign in with GitHub).
3. **New → Web Service** → connect the `box-office-vs-ratings` repo.
4. Render auto-detects Python. Confirm:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:server --bind 0.0.0.0:$PORT --timeout 120`
     *(the `Procfile` sets this automatically)*
   - **Instance type:** Free
5. **Create Web Service.** First build takes ~3–5 min. You'll get a URL like
   `https://box-office-vs-ratings.onrender.com`.

No environment variables are needed (no DB, posters come from the cache).

## On demo day

- The free tier **sleeps after ~15 min idle**; the first hit then takes ~30–60s to wake.
  **Open the URL ~2–3 minutes before you demo** so it's warm.
- It needs internet (venue Wi-Fi). If the Wi-Fi is unreliable, use the local backup below.

## Backup: run it locally (no internet, no database)

On any machine with Python 3.12+:
```
git clone https://github.com/SpencerGoss/box-office-vs-ratings.git
cd box-office-vs-ratings
pip install -r requirements.txt
python app.py            # → http://127.0.0.1:8050  (uses the CSV automatically)
```
