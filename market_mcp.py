"""One local OpenMarkets MCP session, shared by analysis and chart refreshes."""
import asyncio
import json
import logging
import math
import shutil
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime

from jsonschema import validate, ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOLS = ('get_curated_info', 'get_fast_info', 'get_history')
HISTORY_RANGES = {1: ('1mo', '30m'), 5: ('1mo', '30m'), 30: ('1mo', '30m'),
                  90: ('3mo', '1d'), 180: ('6mo', '1d'), 365: ('1y', '1d')}
session = None
startup_error = None
loop = None
cache = {}
chat_tools = {}

async def discover_chat_tools():
    chat_tools.clear()
    cursor = None
    while True:
        page = await asyncio.wait_for(session.list_tools(cursor=cursor), 20)
        for tool in page.tools:
            if tool.name in TOOLS:
                chat_tools[tool.name] = {'type': 'function', 'name': tool.name,
                    'description': (tool.description or '').strip() +
                        ' Read-only OpenMarkets MCP lookup; does not change dashboard cards or lines. '
                        'History returns statistics and at most 80 sampled close prices, with Unix-millisecond timestamps.',
                    'parameters': tool.inputSchema, 'strict': False}
        cursor = page.nextCursor
        if not cursor or len(chat_tools) == len(TOOLS):
            break

@asynccontextmanager
async def lifespan(app):
    global session, loop, startup_error
    loop = asyncio.get_running_loop()
    startup_error = None
    chat_tools.clear()
    async with AsyncExitStack() as stack:
        try:
            installed = shutil.which('openmarkets')
            streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=installed or shutil.which('uvx') or 'uvx',
                args=[] if installed else ['openmarkets@latest'])))
            session = await stack.enter_async_context(ClientSession(*streams))
            await asyncio.wait_for(session.initialize(), 40)
        except Exception as exc:
            session = None
            startup_error = f'OpenMarkets failed to initialise ({type(exc).__name__}). See server startup logs.'
            logging.exception('OpenMarkets MCP startup failed')
        if session is not None:
            try:
                await discover_chat_tools()
            except Exception:
                chat_tools.clear()
                logging.exception('OpenMarkets chat tool discovery failed; chart lookups remain available')
        yield
        session = None
        chat_tools.clear()

async def call(tool, ticker, days=30):
    period, interval = HISTORY_RANGES[days]
    args = {'ticker': ticker}
    if tool == 'get_history':
        args.update(period=period, interval=interval)
    return await call_native(tool, args)

async def call_native(tool, args):
    if tool == 'get_history':
        args = {'period': '1y', 'interval': '1d', **args}
    key = (tool, tuple(sorted(args.items())))
    ttl = 3600 if tool == 'get_curated_info' else 55
    if key in cache and time.monotonic() - cache[key][0] < ttl:
        return cache[key][1]
    result = {'ticker': args['ticker'], 'tool': tool}
    try:
        if session is None:
            result['error'] = startup_error or 'OpenMarkets MCP is not connected.'
            return result
        if tool == 'get_history':
            result.update(period=args['period'], interval=args['interval'])
        response = await asyncio.wait_for(session.call_tool(tool, args), 20)
        if response.isError:
            raise RuntimeError('Provider error')
        data = response.structuredContent
        if data is None:
            blocks = [json.loads(c.text) for c in response.content if c.type == 'text']
            data = blocks[0] if len(blocks) == 1 else blocks
        if isinstance(data, dict) and set(data) == {'result'}:
            data = data['result']
        if tool == 'get_history' and isinstance(data, dict) and 'Date' in data:
            data = [data]
        if not data:
            raise RuntimeError('No data')
        result.update(data=data, fetched=datetime.now().astimezone().isoformat())
        cache[key] = (time.monotonic(), result)
    except Exception:
        result['error'] = 'OpenMarkets data unavailable or timed out.'
    return result

def execute_direct(tool, arguments):
    """Forward a validated native MCP call, returning evidence but no UI action."""
    if tool not in chat_tools or tool not in TOOLS:
        return {'error': 'MCP tool is not available or allowed.'}
    try:
        args = json.loads(arguments)
        validate(args, chat_tools[tool]['parameters'])
    except (ValueError, TypeError, ValidationError):
        return {'error': 'Invalid MCP tool arguments. No lookup made.'}
    if loop is None or not loop.is_running():
        return {'error': 'OpenMarkets MCP is not connected.'}
    future = asyncio.run_coroutine_threadsafe(call_native(tool, args), loop)
    try:
        record = future.result(timeout=25)
    except TimeoutError:
        future.cancel()
        return {'error': 'OpenMarkets MCP lookup timed out.'}
    checks = evidence([record])
    if checks[0].get('error'):
        return {'error': checks[0]['error'], 'checks': checks}
    data = record['data']
    if tool == 'get_history':
        bars = chart_data(args['ticker'], [record])['bars']
        data = {**checks[0]['data'], 'low': min(b['c'] for b in bars), 'high': max(b['c'] for b in bars),
                'sampledBars': bars if len(bars) <= 80 else [bars[round(i*(len(bars)-1)/79)] for i in range(80)]}
    else:
        data = {k: v[:1600] if isinstance(v, str) else v for k, v in data.items()}
    return {'source': 'OpenMarkets MCP', 'data': data, 'checks': checks}

def fetch_batch(tickers, tools=TOOLS, days=30):
    if any(tool not in TOOLS for tool in tools):
        raise ValueError('Tool not allowed')
    if days not in HISTORY_RANGES:
        raise ValueError('History range not allowed')
    async def gather():
        return await asyncio.gather(*(call(tool, ticker, days) for ticker in tickers for tool in tools))
    if loop is None or not loop.is_running():
        return [{'ticker': t, 'tool': name, 'error': 'OpenMarkets is not connected.'} for t in tickers for name in tools]
    future = asyncio.run_coroutine_threadsafe(gather(), loop)
    try:
        return future.result(timeout=25)
    except TimeoutError:
        future.cancel()
        return [{'ticker': t, 'tool': name, 'error': 'OpenMarkets batch timed out.'} for t in tickers for name in tools]

def chart_data(ticker, records):
    parts = {r['tool']: r for r in records if r['ticker'] == ticker}
    history = parts.get('get_history', {}).get('data', [])
    fast = parts.get('get_fast_info', {}).get('data', {})
    bars = []
    for row in history if isinstance(history, list) else []:
        try:
            stamp = datetime.fromisoformat(row['Date'].replace('Z', '+00:00'))
            close = float(row['Close'])
            if stamp.tzinfo and math.isfinite(close) and close > 0:
                bars.append({'t': int(stamp.timestamp()*1000), 'c': close})
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b['t'])
    if not bars:
        return {'ticker': ticker, 'error': parts.get('get_history', {}).get('error') or 'No price bars returned by OpenMarkets.'}
    return {'ticker': ticker, 'bars': bars, 'currency': fast.get('currency') or 'Currency unavailable',
            'exchangeTimezone': fast.get('timezone', 'UTC'), 'exchange': fast.get('exchange'),
            'quote': fast.get('lastPrice') or bars[-1]['c'], 'quoteTime': None,
            'quoteSource': 'get_fast_info' if fast.get('lastPrice') else 'Latest history bar close',
            'updated': parts['get_history']['fetched'], 'source': 'OpenMarkets MCP',
            'interval': parts['get_history'].get('interval', '30m'), 'period': parts['get_history'].get('period', '1mo'),
            'warning': parts.get('get_fast_info', {}).get('error')}

def evidence(records):
    """Keep full bars for charts; send only compact evidence to Luna."""
    out = []
    for record in records:
        item = {k: v for k, v in record.items() if k != 'data'}
        data = record.get('data')
        if record['tool'] == 'get_history' and data:
            chart = chart_data(record['ticker'], records)
            if 'error' not in chart:
                bars = chart['bars']
                item['data'] = {'firstBar': bars[0], 'lastBar': bars[-1], 'bars': len(bars),
                                'periodChangePct': round((bars[-1]['c']/bars[0]['c']-1)*100, 2)}
            else:
                item['error'] = chart['error']
        elif record['tool'] == 'get_curated_info' and isinstance(data, dict):
            item['data'] = {k: v[:1600] if isinstance(v, str) else v for k, v in data.items()
                            if k in ('symbol', 'longName', 'shortName', 'sector', 'industry', 'country', 'longBusinessSummary', 'website') and v is not None}
        elif isinstance(data, dict):
            item['data'] = {k: data[k] for k in ('currency', 'exchange', 'quoteType', 'lastPrice', 'previousClose', 'timezone') if k in data}
        out.append(item)
    return out
