"""Bounded chat tools: read-only MCP data and per-visitor chart actions."""
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import market_mcp

Symbol = Annotated[str, Field(pattern=r'^[A-Z0-9^][A-Z0-9.^=\-]{0,19}$')]
Colour = Literal['blue', 'burgundy', 'green', 'gold', 'purple', 'orange', 'teal', 'gray']


class Comparison(BaseModel):
    ticker: Symbol
    name: str = Field(max_length=128)
    reason: str = Field(max_length=300)


class Profile(BaseModel):
    ticker: Symbol
    name: str = Field(max_length=128)
    sector: str = Field(max_length=100)
    industry: str = Field(max_length=150)
    country: str = Field(max_length=100)
    summary: str = Field(max_length=1600)
    fetched: str = Field(max_length=80)


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Tickers(Arguments):
    tickers: list[Symbol] = Field(min_length=1, max_length=3)


class AddComparisons(Tickers):
    colour: Colour | None = Field(description='Optional colour for the requested tickers; null keeps current colours.')
    days: Literal[1, 5, 30] | None = Field(description='Optional chart range; null keeps the current range.')


class View(Arguments):
    days: Literal[1, 5, 30]
    visible_tickers: list[Symbol] | None = Field(max_length=8, description='Null keeps current visibility; an empty list hides all lines.')


class LineColour(Arguments):
    ticker: Symbol
    colour: Colour


class Lookup(Arguments):
    ticker: Symbol


DEFINITIONS = {
    'add_comparisons': (AddComparisons, 'Add 1–3 exact Yahoo symbols alongside article picks, or show existing symbols. Verify MCP price history first. Include requested colour/range here to complete a combined request without another tool round. Maximum three added comparisons in total.'),
    'remove_comparisons': (Tickers, 'Remove chat-added comparisons only. Original article picks cannot be removed; hide them with set_chart_view.'),
    'set_chart_view': (View, 'Set the chart range to 1, 5, or 30 days and optionally replace the visible ticker selection. All symbols must already be on the dashboard.'),
    'set_line_colour': (LineColour, 'Change the line, legend, and card colour for an existing dashboard ticker using the named palette.'),
    'refresh_prices': (Arguments, 'Refresh quotes and history for all dashboard tickers via OpenMarkets. Provider data can be delayed; its 55-second cache still applies.'),
    'get_security_profile': (Lookup, 'Read a security profile via OpenMarkets and display its name, sector, industry, country, and business summary below the graph. Does not add a chart line.'),
}
TOOLS = [{'type': 'function', 'name': name, 'description': description,
          'parameters': model.model_json_schema(), 'strict': True}
         for name, (model, description) in DEFINITIONS.items()]


@dataclass
class ChartState:
    originals: list[dict]
    comparisons: list[Comparison]
    visible: set[str]
    days: int
    colours: dict[str, Colour] = field(default_factory=dict)

    def symbols(self):
        return [s['ticker'] for s in self.originals] + [s.ticker for s in self.comparisons]


def execute(name, arguments, state):
    """Return compact model evidence separately from a deterministic UI action."""
    if name not in DEFINITIONS:
        return {'error': 'Tool not allowed.'}, None
    try:
        args = DEFINITIONS[name][0].model_validate_json(arguments)
    except (ValidationError, ValueError, TypeError):
        return {'error': 'Invalid tool arguments. No action taken.'}, None
    if name == 'add_comparisons':
        tickers = list(dict.fromkeys(args.tickers))
        new = [t for t in tickers if t not in state.symbols()]
        if len(state.comparisons) + len(new) > 3:
            return {'error': 'Only three added comparisons are allowed. Remove a comparison first.'}, None
        records = market_mcp.fetch_batch(new) if new else []
        checks = market_mcp.evidence(records)
        prices, errors = [], {}
        added = []
        for ticker in new:
            price = market_mcp.chart_data(ticker, records)
            if price.get('error'):
                errors[ticker] = price['error']
                continue
            info = next((r.get('data', {}) for r in records if r['ticker'] == ticker and r['tool'] == 'get_curated_info'), {})
            info = info if isinstance(info, dict) else {}
            title = info.get('longName') or info.get('shortName') or ticker
            comparison = Comparison(ticker=ticker, name=str(title)[:128], reason='Added at your request for comparison.')
            state.comparisons.append(comparison)
            added.append(comparison.model_dump())
            prices.append(price)
        shown = [t for t in tickers if t in state.symbols()]
        state.visible.update(shown)
        colours = {t: args.colour for t in shown} if args.colour else {}
        state.colours.update(colours)
        if shown and args.days is not None:
            state.days = args.days
        result = {'added': added, 'shown': shown, 'errors': errors, 'checks': checks,
                  'colours': colours, 'days': state.days}
        return result, {'type': name, 'comparisons': added, 'prices': prices, 'shown': shown,
                        'colours': colours, 'days': state.days}
    if name == 'remove_comparisons':
        originals = {s['ticker'] for s in state.originals}
        if originals.intersection(args.tickers):
            return {'error': 'Original article picks cannot be removed. Use set_chart_view to hide them.'}, None
        removed = [s.ticker for s in state.comparisons if s.ticker in args.tickers]
        state.comparisons = [s for s in state.comparisons if s.ticker not in removed]
        state.visible.difference_update(removed)
        for ticker in removed:
            state.colours.pop(ticker, None)
        return {'removed': removed}, {'type': name, 'tickers': removed}
    if name == 'set_chart_view':
        if args.visible_tickers is not None:
            if set(args.visible_tickers) - set(state.symbols()):
                return {'error': 'Visible tickers must already be on the dashboard. Add comparisons first.'}, None
            state.visible = set(args.visible_tickers)
        state.days = args.days
        view = {'days': state.days, 'visible_tickers': [t for t in state.symbols() if t in state.visible]}
        return view, {'type': name, **view}
    if name == 'set_line_colour':
        if args.ticker not in state.symbols():
            return {'error': 'Ticker is not on the dashboard.'}, None
        state.colours[args.ticker] = args.colour
        return args.model_dump(), {'type': name, **args.model_dump()}
    if name == 'refresh_prices':
        records = market_mcp.fetch_batch(state.symbols(), ('get_fast_info', 'get_history'))
        prices = [market_mcp.chart_data(t, records) for t in state.symbols()]
        return {'checks': market_mcp.evidence(records), 'note': 'Fetch times are not trade times; provider/cache delays still apply.'}, {'type': name, 'prices': prices}
    records = market_mcp.fetch_batch([args.ticker], ('get_curated_info',))
    checks = market_mcp.evidence(records)
    info = records[0].get('data') if records else None
    if not isinstance(info, dict) or not any(info.get(k) for k in ('longName', 'shortName', 'longBusinessSummary')):
        return {'error': 'OpenMarkets did not return a usable security profile.', 'checks': checks}, None
    profile = Profile(ticker=args.ticker, name=str(info.get('longName') or info.get('shortName') or args.ticker)[:128],
                      sector=str(info.get('sector') or '')[:100], industry=str(info.get('industry') or '')[:150],
                      country=str(info.get('country') or '')[:100], summary=str(info.get('longBusinessSummary') or '')[:1600],
                      fetched=str(records[0].get('fetched') or '')[:80]).model_dump()
    return {'profile': profile, 'checks': checks}, {'type': name, 'profile': profile}
