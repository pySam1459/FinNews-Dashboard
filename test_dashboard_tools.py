"""Offline tool execution and two-request Responses contract checks."""
import asyncio
import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import dashboard_tools as t
import news_dashboard as d


def records(tickers, tools=t.market_mcp.TOOLS, days=30):
    data = {'get_curated_info': {'longName': 'Test security', 'sector': 'Energy', 'longBusinessSummary': 'Produces energy.'},
            'get_fast_info': {'lastPrice': 110, 'currency': 'USD'},
            'get_history': [{'Date': '2026-10-01T10:00:00Z', 'Close': 100}, {'Date': '2026-10-02T10:00:00Z', 'Close': 110}]}
    return [{'ticker': ticker, 'tool': tool, 'fetched': '2026-10-03T10:00:00Z',
             **({'error': 'Unknown symbol'} if ticker == 'MISSING' else {'data': data[tool]})}
            for ticker in tickers for tool in tools]


def run():
    # Mixed original picks and chat comparisons must all disappear, not be hidden.
    original_picks = [{'ticker': '^FTSE'}, {'ticker': 'VLO'}, {'ticker': 'XOM'}]
    removal = t.ChartState(original_picks, [t.Comparison(ticker='BP', name='BP', reason='Comparison')],
                           {'^FTSE', 'VLO', 'BP', 'XOM'}, 5)
    removed, action = t.execute('remove_comparisons', json.dumps({'tickers': ['^FTSE', 'BP', 'VLO']}), removal)
    assert removal.symbols() == ['XOM'], 'Removing mixed picks must delete all requested tickers, not hide them'
    assert set(removed['removed']) == {'^FTSE', 'BP', 'VLO'} and set(action['tickers']) == set(removed['removed'])
    assert original_picks == [{'ticker': '^FTSE'}, {'ticker': 'VLO'}, {'ticker': 'XOM'}]
    with patch.object(t.market_mcp, 'fetch_batch', side_effect=records):
        restored, restore_action = t.execute('add_comparisons', json.dumps({'tickers': ['VLO'], 'colour': None, 'days': None}), removal)
        assert restored['restored'] == ['VLO'] and restore_action['restored'] == ['VLO']
        assert removal.symbols() == ['VLO', 'XOM'] and not removal.comparisons
    # Idempotent removal, including every remaining ticker.
    t.execute('remove_comparisons', json.dumps({'tickers': ['VLO', 'XOM']}), removal)
    assert not removal.symbols() and not removal.visible
    assert t.execute('remove_comparisons', json.dumps({'tickers': ['VLO', 'XOM']}), removal)[0]['removed'] == []
    originals = [{'ticker': 'XOM'}]
    state = t.ChartState(originals, [], {'XOM'}, 5)
    def execute(name, **args):
        if name == 'add_comparisons':
            args = {'colour': None, 'days': None, **args}
        return t.execute(name, json.dumps(args), state)
    with patch.object(t.market_mcp, 'fetch_batch', side_effect=records) as fetch:
        result, action = execute('add_comparisons', tickers=['^FTSE', 'MISSING'], colour='gold', days=30)
        assert state.symbols() == ['XOM', '^FTSE'] and state.visible == {'XOM', '^FTSE'}
        assert result['errors'] == {'MISSING': 'Unknown symbol'} and len(action['prices'][0]['bars']) == 2
        assert action['colours'] == {'^FTSE': 'gold'} and state.days == 30
        assert 'prices' not in result and 'bars' not in json.dumps(result['added'])
        assert 'firstBar' in json.dumps(result['checks']), 'Model receives compact history evidence'
        fetch.reset_mock()
        execute('add_comparisons', tickers=['^FTSE', '^FTSE'])
        assert len(state.comparisons) == 1 and fetch.call_count == 0
        execute('set_chart_view', days=30, visible_tickers=['^FTSE'])
        assert state.days == 30 and state.visible == {'^FTSE'}
        execute('set_line_colour', ticker='^FTSE', colour='gold')
        assert state.colours == {'^FTSE': 'gold'}
        unchanged = deepcopy(state)
        for name, args in [('set_chart_view', {'days': 1, 'visible_tickers': ['BAD']}),
                           ('set_line_colour', {'ticker': '^FTSE', 'colour': 'url(javascript:x)'}),
                           ('add_comparisons', {'tickers': ['BAD;DELETE']}),
                           ('add_comparisons', {'tickers': ['A'], 'extra': 1}),
                           ('delete', {})]:
            assert execute(name, **args)[1] is None
            assert state == unchanged
        assert t.execute('add_comparisons', '{', state)[1] is None
        execute('add_comparisons', tickers=['AAPL', 'MSFT'])
        assert execute('add_comparisons', tickers=['NVDA'])[1] is None
        execute('remove_comparisons', tickers=['^FTSE'])
        assert '^FTSE' not in state.symbols() and not state.colours
        execute('set_chart_view', days=1, visible_tickers=[])
        assert not state.visible
        execute('set_chart_view', days=5, visible_tickers=None)
        assert not state.visible and state.days == 5
        profile, action = execute('get_security_profile', ticker='XOM')
        assert profile['profile']['sector'] == 'Energy' and action['type'] == 'get_security_profile'
        assert execute('get_security_profile', ticker='MISSING')[1] is None
        evidence, action = execute('refresh_prices')
        assert len(action['prices']) == 3 and len(evidence['checks']) == 6
        assert originals == [{'ticker': 'XOM'}], 'Visitor changes must never mutate cached article picks'
        fetch.reset_mock()
        result, action = execute('set_chart_view', days=365, visible_tickers=None)
        assert fetch.call_args.kwargs['days'] == 365 and state.days == 365 and len(action['prices']) == 3
        assert len(result['checks']) == 6
        execute('refresh_prices')
        assert fetch.call_args.kwargs['days'] == 365
        unchanged = deepcopy(state)
        with patch.object(t.market_mcp, 'fetch_batch', return_value=[]):
            assert execute('set_chart_view', days=180, visible_tickers=None)[1] is None
            assert state == unchanged, 'Failed history lookup must keep previous range and selection'
        assert execute('set_chart_view', days=999, visible_tickers=None)[1] is None
        unchanged = deepcopy(state)
        assert execute('add_comparisons', tickers=['MISSING'], days=180)[1] is None
        assert state == unchanged, 'Failed addition must not replace existing history with another resolution'
        # A new benchmark added with a longer range must refresh existing lines too.
        state.days = 5
        result, action = execute('add_comparisons', tickers=['^FTSE'], days=180)
        assert fetch.call_args.kwargs['days'] == 180 and set(fetch.call_args.args[0]) == {'XOM', 'AAPL', 'MSFT', '^FTSE'}
        assert len(action['prices']) == 4 and state.days == 180
    for tool in t.TOOLS:
        schema = tool['parameters']
        assert tool['strict'] and schema['additionalProperties'] is False
        assert set(schema.get('required', [])) == set(schema['properties'])

    async def check_stream():
        story = {'id': 'test', 'title': 'Oil story'}
        analysis = {'summary': 'Oil exposure', 'securities': originals, 'events': [], 'mcpChecks': []}
        body = {'id': 'test', 'days': 5, 'rangeStart': '', 'rangeEnd': '', 'prices': [],
                'messages': [{'role': 'user', 'content': 'Add FTSE 100 and make it gold.'}]}
        reasoning = SimpleNamespace(type='reasoning', encrypted_content='test')
        calls = [SimpleNamespace(type='function_call', name=name, call_id=str(i), arguments=json.dumps(args))
                 for i, (name, args) in enumerate([
                     ('add_comparisons', {'tickers': ['^FTSE'], 'colour': 'gold', 'days': 30}),
                     ('set_line_colour', {'ticker': '^FTSE', 'colour': 'gold'}),
                     ('set_chart_view', {'days': 30, 'visible_tickers': ['XOM', '^FTSE']}),
                     ('get_security_profile', {'ticker': 'XOM'}),
                     ('refresh_prices', {})])]
        first, second = MagicMock(), MagicMock()
        first.__iter__.return_value = []
        first.get_final_response.return_value = SimpleNamespace(status='completed', output=[reasoning, *calls])
        second.__iter__.return_value = [SimpleNamespace(type='response.output_text.delta', delta='Added FTSE; refresh exceeded the four-tool limit.')]
        second.get_final_response.return_value = SimpleNamespace(status='completed', output=[])
        with patch.dict(d.os.environ, {'OAI_KEY': 'test-only'}), patch.object(d, 'stories', {'test': story}), \
             patch.object(d, 'analyses', {'test': analysis}), patch.object(d, 'OpenAI') as sdk, \
             patch.object(t.market_mcp, 'fetch_batch', side_effect=records) as fetch:
            client = sdk.return_value.__enter__.return_value
            client.responses.stream.side_effect = [nullcontext(first), nullcontext(second)]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=d.app), base_url='http://localhost') as http:
                response = await http.post('/api/chat/stream', json=body)
                events = [json.loads(line) for line in response.text.splitlines()]
                actions = [e['action'] for e in events if e['type'] == 'action']
                assert [a['type'] for a in actions] == ['add_comparisons', 'set_line_colour', 'set_chart_view', 'get_security_profile']
                assert events[-1] == {'type': 'complete'} and client.responses.stream.call_count == 2
                args = client.responses.stream.call_args.kwargs
                assert args['tool_choice'] == 'none' and args['store'] is False
                assert args['include'] == ['reasoning.encrypted_content']
                assert args['input'][2] is reasoning and args['input'][3:8] == calls
                outputs = [i for i in args['input'] if isinstance(i, dict) and i.get('type') == 'function_call_output']
                assert len(outputs) == 5 and json.loads(outputs[-1]['output'])['error'].startswith('Four-tool')
                assert json.loads(outputs[-1]['output'])['chart'] == {'tickers': ['XOM', '^FTSE'], 'days': 30,
                                                                      'colours': {'^FTSE': 'gold'}, 'visible_tickers': ['XOM', '^FTSE']}
                assert fetch.call_count == 2 and analysis['securities'] == originals
                # Comparison state is validated before any billable request.
                for invalid in [
                    {**body, 'comparisons': [{'ticker': 'XOM', 'name': 'duplicate', 'reason': ''}]},
                    {**body, 'comparisons': [{'ticker': '^FTSE', 'name': 'index', 'reason': ''}] * 2},
                    {**body, 'colours': {'AAPL': 'gold'}},
                    {**body, 'removed': ['AAPL']},
                ]:
                    assert (await http.post('/api/chat/stream', json=invalid)).status_code == 400
                assert client.responses.stream.call_count == 2
                # Removed originals stay removed across follow-ups, without changing the cache.
                no_tools = MagicMock()
                no_tools.__iter__.return_value = [SimpleNamespace(type='response.output_text.delta', delta='No tickers selected.')]
                no_tools.get_final_response.return_value = SimpleNamespace(status='completed', output=[])
                client.responses.stream.side_effect = [nullcontext(no_tools)]
                followup = await http.post('/api/chat/stream', json={**body, 'removed': ['XOM'], 'days': 365})
                assert json.loads(followup.text.splitlines()[-1])['type'] == 'complete'
                context = json.loads(client.responses.stream.call_args.kwargs['input'][0]['content'].split('\n', 1)[1])
                assert context['browserSnapshot']['removed'] == ['XOM'] and analysis['securities'] == originals
                with patch.object(d, 'price_data', return_value={'ticker': 'XOM', 'bars': []}) as prices:
                    for days in (1, 5, 30, 90, 180, 365):
                        assert (await http.get('/api/prices', params={'tickers': 'XOM', 'days': days})).status_code == 200
                        assert prices.call_args.args == ('XOM', days)
                    count = prices.call_count
                    assert (await http.get('/api/prices', params={'tickers': 'XOM', 'days': 999})).status_code == 400
                    assert prices.call_count == count
    asyncio.run(check_stream())
    print('Dashboard tool checks passed.')
