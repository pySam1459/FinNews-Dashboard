# News / Markets

Start from this folder:

```powershell
uv run news_dashboard.py
```

Open http://127.0.0.1:8766. Keep the process running while using the dashboard.
The frontend is `news-first.html`, with inline CSS and JavaScript. A local Python
backend is necessary for the OpenAI key and OpenMarkets data; this version is not an
offline HTML snapshot. The earlier dashboard remains in the parent folder.

The server loads `OAI_KEY` from `.env`, never serves that file, and uses the
OpenAI Responses API with `gpt-5.6-luna`, low reasoning effort and structured
output. Its short instruction is `PROMPT` in `news_dashboard.py`. It returns
brief exposure hypotheses, not internal reasoning. The summary streams into the
page as Luna writes it; tickers and dates appear after final schema validation.
Luna streams a draft and chooses candidates. The backend then calls OpenMarkets
`get_curated_info`, `get_fast_info`, and `get_history` in one parallel batch.
One short second Luna request refines the summary and selections using that evidence;
it cannot introduce new symbols. There is no iterative research loop. The UI shows
successful and failed MCP checks. Each new analysis uses up to two API requests;
results are cached in memory until server restart.

`market_mcp.py` launches one local `uvx openmarkets@latest` stdio server using the
Python MCP SDK v1. This is independent of the Codex connection; `uvx` must be on
PATH, and first startup may download dependencies. The backend orchestrates tools
for Luna's candidates, rather than exposing unrestricted tool access to the model.
Profiles are cached for one hour; quotes/history for 55 seconds and reused by
charts. Luna receives compact history statistics, not full chart arrays.

Checks: `uv run news_dashboard.py --self-test` (offline) and
`uv run news_dashboard.py --check-prices` (live MCP, no OpenAI credits).

BBC business/world RSS supplies the news. The server extracts article text when
available and explicitly labels summary-only analysis otherwise. Article text
is sent to OpenAI for analysis. Dates require a supporting quote present in that
text; ambiguous dates stay unplaced. Date-only events shade a UTC calendar day.
Events outside the price window remain listed rather than being placed at a
misleading point on the graph.

OpenMarkets MCP (Yahoo upstream) supplies prices and one month of 30-minute bars. News refreshes
every three minutes and prices every minute while the tab is visible. These
are polling intervals, not a guarantee of exchange real-time data. Fast quotes do
not supply trade timestamps; fetch times must not be interpreted as trade times.
Unknown tickers and unavailable data have explicit
error states. This is a local personal research prototype.

## Deployment

Use the GitHub repository as source control and deploy the included `render.yaml`
as a Render Blueprint. GitHub Pages cannot run this FastAPI/OpenMarkets backend.
Set `OAI_KEY` only in Render's secret environment settings. `DEMO_PASSWORD` is an
optional HTTP Basic Auth password for a shareable demo link and is recommended to
prevent uninvited visitors spending the API budget. Render supplies its hostname
to the app; add custom domains through `ALLOWED_HOSTS` if needed.
