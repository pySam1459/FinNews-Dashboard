# FinNews Dashboard

An article-to-markets demo: GPT-5.6 Luna proposes related securities, then one
parallel OpenMarkets MCP round verifies profile, quote, and history data before a
short final refinement. This is research/demo software, not investment advice.

The news feed is first screened by Luna: up to 12 significant market stories,
ranked by likely impact, with a short reason per headline. One cached batch
request screens changed feeds; article analysis still uses its own two requests.

## Run locally

Copy `.env.example` to `.env`, set `OAI_KEY`, then run:

```powershell
uv run news_dashboard.py
```

Open `http://127.0.0.1:8766`. More implementation detail is in
[`NEWS-DASHBOARD.md`](NEWS-DASHBOARD.md).

## Share it publicly

GitHub stores the source and deploy configuration; it does not run this backend.
GitHub Pages cannot be used because the dashboard needs a server-side OpenAI key
and a local OpenMarkets MCP process.

This repository includes a Render Blueprint. In Render, choose **New → Blueprint**,
connect this GitHub repository, and select `render.yaml`. Add this secret in the
Render environment settings (never commit it):

- `OAI_KEY` — the OpenAI API key used for Luna requests.

Render creates an `onrender.com` URL after deployment and redeploys from future
pushes to `main`. Its free plan may have a cold start. If the prepaid credit or
spend limit is exhausted, the dashboard clearly pauses new analyses rather than
retrying them. See
[Render's FastAPI deployment guide](https://render.com/docs/deploy-fastapi).
