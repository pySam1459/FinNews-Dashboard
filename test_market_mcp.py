"""Offline contract checks: uv run news_dashboard.py --self-test."""
import asyncio
from types import SimpleNamespace
import market_mcp as m

def run():
    rows = [{'Date': '2026-09-10T12:00:00Z', 'Close': 100},
            {'Date': '2026-09-11T12:00:00Z', 'Close': 110},
            {'Date': 'bad', 'Close': 123}]
    records = [{'ticker': 'XOM', 'tool': 'get_history', 'data': rows, 'fetched': '2026-09-11T12:01:00Z'},
               {'ticker': 'XOM', 'tool': 'get_fast_info', 'data': {'lastPrice': 111, 'currency': 'USD'}}]
    chart = m.chart_data('XOM', records)
    assert len(chart['bars']) == 2 and chart['quote'] == 111 and chart['quoteTime'] is None
    assert m.evidence(records)[0]['data']['periodChangePct'] == 10
    assert m.chart_data('XOM', records[:1])['quote'] == 110
    assert 'error' in m.chart_data('XOM', [])
    try:
        m.fetch_batch(['XOM'], ['delete'])
        raise AssertionError('Unknown tool accepted')
    except ValueError:
        pass
    async def check_cache():
        class FakeSession:
            calls = 0
            async def call_tool(self, name, args):
                self.calls += 1
                return SimpleNamespace(isError=False, structuredContent={'result': rows})
        fake = FakeSession()
        m.session = fake
        try:
            first = await m.call('get_history', 'XOM')
            second = await m.call('get_history', 'XOM')
            assert first == second and fake.calls == 1 and first['data'] == rows
            m.session = None
            assert 'error' in await m.call('get_history', 'MISSING')
        finally:
            m.session = None
            m.cache.clear()
    asyncio.run(check_cache())
    print('Offline MCP checks passed.')
