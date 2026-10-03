# FinNews Dashboard

An article-to-markets demo: GPT-6 Luna proposes related securities, then one
parallel OpenMarkets MCP round verifies profile, quote, and history data before a
short final refinement. This is research/demo software, not investment advice.

The news feed is first screened by Luna: up to 12 significant market stories,
ranked by likely impact, with a short reason per headline. One cached batch
request screens changed feeds; article analysis still uses its own two requests.

After selecting a story, use **Ask Luna** directly below the summary to ask
questions or follow-ups. Replies stream from the same model using the displayed
story, analysis, MCP evidence, and current chart snapshot. Ask it to add a benchmark,
change the chart, refresh prices, or look up a company through OpenMarkets MCP.
Ordinary questions use one API request. Tool requests use at most two requests
and four tool calls. Chat stays in page memory and resets
when you select another story or reload the page.

Try: “Add the FTSE 100 alongside these tickers and make its line gold”,
“Show only XOM and the FTSE for the last month”, or “Show me XOM's company profile”.
You can add up to three comparison securities without replacing the article picks.
Ask Luna to remove any dashboard ticker, including an article pick. Removal deletes
its card and line; hiding a line is a separate action. You can restore a removed
ticker by asking Luna to add it again.
Chart ranges reach one year, with daily bars for 3-month, 6-month, and 1-year views.
Tool activity appears within each Luna reply. Enter sends a question;
Ctrl/Cmd + Enter inserts a new line.
Changes affect only your dashboard, not other visitors. Clearing chat keeps your
chart changes; selecting another story resets them.

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
