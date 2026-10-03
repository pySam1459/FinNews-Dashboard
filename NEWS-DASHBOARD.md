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
OpenAI Responses API with `gpt-6-luna`, low reasoning effort and structured
output. Its short instruction is `PROMPT` in `news_dashboard.py`. It returns
brief exposure hypotheses, not internal reasoning. The summary streams into the
page as Luna writes it; tickers and dates appear after final schema validation.
Luna streams a draft and chooses candidates. The backend then calls OpenMarkets
`get_curated_info`, `get_fast_info`, and `get_history` in one parallel batch.
One short second Luna request refines the summary and selections using that evidence;
it cannot introduce new symbols. There is no iterative research loop. The UI shows
successful and failed MCP checks. Each new analysis uses up to two API requests;
results are cached in memory until server restart.

The **Ask Luna** panel directly below the summary streams replies from
`/api/chat/stream`. Each question sends the current chart range, shown/hidden
securities, latest displayed quotes, and up to 80 sampled bars per visible
security with the full range's high and low. The backend adds its cached article
metadata, analysis, date annotations, and MCP evidence. It does not fetch more
article text. Luna must acknowledge summary-only coverage,
missing timestamps, and the difference between exposure and causation.

Chat uses one Responses API call for ordinary questions. Requests that need tools
use one bounded tool round (at most four calls), followed by a second streamed
answer with further calls disabled. Both requests use low reasoning effort, a
1,600-token output limit, no retries, and `store=False`. Encrypted reasoning and
output items from the first request accompany the tool results in the second.
The latest five completed turns are
sent with the next question. Conversation history lives only in page memory;
selecting another story, clearing chat, or reloading removes it. Questions and
dashboard context are sent to OpenAI. API credit-limit errors also appear in chat.

### Chat tools

| Example request | Tool | Result |
| --- | --- | --- |
| Add the FTSE 100 and make its line gold for the last month | `add_comparisons` | Checks MCP profile, quote, and history, then adds a card and percentage-change line with the requested colour and range. |
| Remove FTSE, BP, and VLO | `remove_comparisons` | Deletes all requested cards and lines, including original article picks, without changing the shared analysis. |
| Show XOM for the last year | `set_chart_view` | Sets 1-, 5-, 30-, 90-, 180-, or 365-day range and visible tickers. Fetches MCP history when the history period or interval changes. |
| Make the FTSE line gold | `set_line_colour` | Changes the card, line, and legend using an eight-colour palette. |
| Refresh the prices | `refresh_prices` | Reads MCP quotes and history; the 55-second cache and provider delays still apply. |
| Show XOM's company profile | `get_security_profile` | Displays the latest requested profile below the chart and MCP checks. |
| Check BP's valuation without changing the graph | `get_curated_info` | Native MCP lookup returns curated fundamentals, including available valuation and financial metrics. |
| Look up BP's latest quote without adding it | `get_fast_info` | Native MCP lookup returns available price, currency, exchange, volume, and market statistics. |
| How did BP move over three months? | `get_history` | Native MCP lookup accepts `ticker`, `period`, and `interval`. Returns first and last bars, percentage change, close-price high and low, and up to 80 sampled prices. Does not change the graph. |

`dashboard_tools.py` validates arguments against strict function schemas. There
is no arbitrary code, CSS, browser navigation, or trading tool. Full price arrays
go to the chart, while Luna receives compact MCP evidence. Failed ticker lookups
do not add empty chart lines. Partial successes are reported in tool activity and
the answer. The MCP checks widget includes checks requested through chat.

At startup, the server discovers these three native tools through MCP `list_tools`.
Their names and input schemas are sent to Luna alongside the six dashboard tools.
Native schemas retain their optional parameters with `strict=False`; the server
validates every model-generated call against the discovered schema before calling
MCP `call_tool`. The three-tool allowlist prevents access to the rest of the MCP
catalogue. Native lookups return evidence only, never dashboard actions. Profile
and quote results preserve available native fields, with strings capped at 1,600
characters. History is sampled rather than sending full arrays to the model.
Native lookups share the existing cache, timeouts, and four-call limit with dashboard
controls. A lookup's price can differ from the plotted snapshot; research does not
refresh or redraw the chart. `/api/health` lists discovered tools in `chatMcpTools`.

The browser owns up to three added comparisons (eight securities total), visibility,
range, line colours, and the displayed profile. Each question sends this bounded
state to the server. Tool actions update only that visitor's page, never the shared
article-analysis cache. Selecting another story or reloading resets chart additions
and chat. Removed original picks stay excluded on later chat requests and price
refreshes. Asking Luna to add one again restores it without consuming a comparison
slot. Clearing chat removes the conversation, but keeps chart changes.

Tool calls appear within the Luna reply that requested them. Each call's progress
row updates in place and stays with that reply. The conversation scrolls without
a visible scrollbar; keyboard focus and wheel scrolling remain available.
Enter sends chat. Ctrl/Cmd + Enter or Shift + Enter inserts a new line.
Submitting clears the input immediately. A failed reply restores the question for
retry. Plain-language chart requests select the dashboard controls without requiring
tool names; native MCP lookups only gather evidence.

`market_mcp.py` launches one local OpenMarkets stdio server using the Python MCP
SDK v1. Docker installs the server during the build, so deployment startup does
not download its dependencies. Local runs use the installed `openmarkets` command
when available, otherwise `uvx openmarkets@latest`. This is independent of the
Codex connection. The backend orchestrates tools for the initial article analysis;
chat Luna can also select the three allowlisted native MCP tools directly.
Profiles are cached for one hour; quotes/history for 55 seconds and reused by
charts. Luna receives compact history statistics, not full chart arrays.

Checks: `uv run news_dashboard.py --self-test` (offline) and
`uv run news_dashboard.py --check-prices` (live MCP, no OpenAI credits).
`uv run news_dashboard.py --check-chat-mcp` uses OpenAI credits to verify that
Luna calls all three native MCP tools and answers without changing the dashboard.
It also checks plain-language ticker additions, including an earlier mistaken refusal.
`node test_chat_input.cjs` checks immediate input clearing, failure recovery, and
cancellation using the actual inline submission handler, without API calls.

BBC business/world RSS supplies the news. The server extracts article text when
available for selected stories. Before headlines reach the feed, Luna screens a
batch of up to 60 headlines, publication dates, and short feed summaries. It picks
up to 12 significant market developments, ranked by likely market significance,
with a short reason for each. Duplicate coverage and low-impact stories are
excluded. This screening is a separate model request from the two per-article
requests. The server checks feeds every three minutes, reuses the shortlist when
the candidate batch is unchanged, and shares that cache across visitors in the
same server process. Failed screenings retain the last audited shortlist with a
warning (or report an error if none exists); unaudited news is never substituted.

The server extracts article text when
available and explicitly labels summary-only analysis otherwise. Article text
is sent to OpenAI for analysis. Dates require a supporting quote present in that
text; ambiguous dates stay unplaced. Date-only events shade a UTC calendar day.
Events outside the price window remain listed rather than being placed at a
misleading point on the graph.

OpenMarkets MCP (Yahoo upstream) supplies prices and history. Views through 30 days
use `period=1mo, interval=30m`. Longer views request `3mo`, `6mo`, or `1y` with
`interval=1d`; the graph labels this daily resolution. The history cache includes
period and interval, so one visitor's long-range view cannot overwrite another's
intraday data. Switching ranges reloads prices, and stale responses from previous
ranges or ticker selections are discarded. Missing long-range history reports an
error rather than extending a short dataset across an empty year. News refreshes
every three minutes and prices every minute while the tab is visible. These
are polling intervals, not a guarantee of exchange real-time data. Fast quotes do
not supply trade timestamps; fetch times must not be interpreted as trade times.
Unknown tickers and unavailable data have explicit
error states. This is a local personal research prototype.

## Deployment

Use the GitHub repository as source control and deploy the included `render.yaml`
as a Render Blueprint. GitHub Pages cannot run this FastAPI/OpenMarkets backend.
Set `OAI_KEY` only in Render's secret environment settings. If the prepaid credit
or spend limit is exhausted, the dashboard visibly pauses new analyses rather than
retrying them. Render supplies its hostname to the app; add custom domains through
`ALLOWED_HOSTS` if needed.
