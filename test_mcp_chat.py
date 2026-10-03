"""Native MCP discovery, argument validation and chat routing checks."""
import asyncio
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import market_mcp as m
import news_dashboard as d


def run():
    async def checks():
        ticker = {'type': 'string', 'minLength': 1, 'maxLength': 32}
        schemas = {name: {'type': 'object', 'properties': {'ticker': ticker},
                         'required': ['ticker'], 'additionalProperties': False} for name in m.TOOLS}
        schemas['get_history']['properties'].update(
            period={'type': 'string', 'enum': ['1mo', '3mo', '1y', '2y'], 'default': '1y'},
            interval={'type': 'string', 'enum': ['30m', '1d'], 'default': '1d'})
        tools = [SimpleNamespace(name=name, description='Native MCP ' + name, inputSchema=schemas[name]) for name in m.TOOLS]
        rows = [{'Date': (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
                 'Close': 100 + i} for i in range(200)]

        class Session:
            def __init__(self):
                self.calls = []
            async def list_tools(self, cursor=None):
                if cursor is None:
                    return SimpleNamespace(tools=[tools[0], SimpleNamespace(name='delete', description='Forbidden')], nextCursor='next')
                assert cursor == 'next'
                return SimpleNamespace(tools=tools[1:], nextCursor=None)
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                if args['ticker'] == 'MISSING':
                    return SimpleNamespace(isError=True, structuredContent=None)
                data = {'get_curated_info': {'longName': 'Test company', 'trailingPE': 18, 'beta': 1.2,
                                            'longBusinessSummary': 'x' * 2000},
                        'get_fast_info': {'lastPrice': 110, 'currency': 'USD', 'marketCap': 123456},
                        'get_history': {'result': rows}}[name]
                return SimpleNamespace(isError=False, structuredContent=data)

        fake = Session()
        with patch.object(m, 'session', fake), patch.object(m, 'loop', asyncio.get_running_loop()), \
             patch.object(m, 'chat_tools', {}), patch.object(m, 'cache', {}):
            await m.discover_chat_tools()
            assert set(m.chat_tools) == set(m.TOOLS) and 'delete' not in m.chat_tools
            assert m.chat_tools['get_history']['parameters'] == schemas['get_history']
            assert m.chat_tools['get_history']['strict'] is False, 'Preserve optional native MCP arguments'
            for name, args in [('delete', {}), ('get_fast_info', {'ticker': ''}),
                               ('get_fast_info', {'ticker': 'BP', 'url': 'http://private'}),
                               ('get_history', {'ticker': 'BP', 'period': 'invalid'}),
                               ('get_history', {'ticker': 'BP', 'interval': None})]:
                result = await asyncio.to_thread(m.execute_direct, name, json.dumps(args))
                assert 'error' in result
            assert not fake.calls, 'Invalid and unlisted calls must not reach MCP'
            assert 'error' in m.execute_direct('get_fast_info', '{')
            fundamentals = await asyncio.to_thread(m.execute_direct, 'get_curated_info', '{"ticker":"BP"}')
            assert fundamentals['data']['trailingPE'] == 18 and fundamentals['data']['beta'] == 1.2
            assert len(fundamentals['data']['longBusinessSummary']) == 1600
            quote = await asyncio.to_thread(m.execute_direct, 'get_fast_info', '{"ticker":"BP"}')
            assert quote['data']['marketCap'] == 123456 and quote['checks'][0]['tool'] == 'get_fast_info'
            calls = len(fake.calls)
            await m.call('get_fast_info', 'BP')
            assert len(fake.calls) == calls, 'Native lookups and dashboard reads must share the cache'
            history = await asyncio.to_thread(m.execute_direct, 'get_history', '{"ticker":"BP","period":"2y","interval":"1d"}')
            assert fake.calls[-1][1] == {'ticker': 'BP', 'period': '2y', 'interval': '1d'}
            assert history['data']['bars'] == 200 and len(history['data']['sampledBars']) == 80
            assert history['data']['low'] == 100 and history['data']['high'] == 299
            assert history['data']['sampledBars'][0]['c'] == 100 and history['data']['sampledBars'][-1]['c'] == 299
            await asyncio.to_thread(m.execute_direct, 'get_history', '{"ticker":"XOM"}')
            assert fake.calls[-1][1] == {'ticker': 'XOM', 'period': '1y', 'interval': '1d'}
            missing = await asyncio.to_thread(m.execute_direct, 'get_history', '{"ticker":"MISSING"}')
            assert 'error' in missing and 'error' in missing['checks'][0]
            with patch.object(m, 'loop', None):
                assert 'not connected' in m.execute_direct('get_fast_info', '{"ticker":"BP"}')['error']

            story = {'id': 'test', 'title': 'Test energy story'}
            analysis = {'summary': 'Potential energy exposure', 'securities': [{'ticker': 'XOM'}], 'events': [], 'mcpChecks': []}
            original = deepcopy(analysis)
            body = {'id': 'test', 'days': 5, 'rangeStart': '', 'rangeEnd': '', 'prices': [],
                    'messages': [{'role': 'user', 'content': 'Look up BP fundamentals, quote and three-month history, without changing the graph.'}]}
            calls = [SimpleNamespace(type='function_call', name=name, call_id=str(i), arguments=json.dumps(args))
                     for i, (name, args) in enumerate([
                         ('get_curated_info', {'ticker': 'BP'}), ('get_fast_info', {'ticker': 'BP'}),
                         ('get_history', {'ticker': 'BP', 'period': '3mo', 'interval': '1d'})])]
            first, second = MagicMock(), MagicMock()
            first.__iter__.return_value = []
            first.get_final_response.return_value = SimpleNamespace(status='completed', output=calls)
            second.__iter__.return_value = [SimpleNamespace(type='response.output_text.delta', delta='BP evidence returned. Graph unchanged.')]
            second.get_final_response.return_value = SimpleNamespace(status='completed', output=[])
            with patch.dict(d.os.environ, {'OAI_KEY': 'test-only'}), patch.object(d, 'stories', {'test': story}), \
                 patch.object(d, 'analyses', {'test': analysis}), patch.object(d, 'OpenAI') as sdk:
                client = sdk.return_value.__enter__.return_value
                client.responses.stream.side_effect = [nullcontext(first), nullcontext(second)]
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=d.app), base_url='http://localhost') as http:
                    response = await http.post('/api/chat/stream', json=body)
                    events = [json.loads(line) for line in response.text.splitlines()]
                    assert events[-1] == {'type': 'complete'} and not any(e['type'] == 'action' for e in events)
                    assert [e['tool'] for e in events if e['type'] == 'tool' and e['status'] == 'completed'] == list(m.TOOLS)
                    assert client.responses.stream.call_count == 2 and analysis == original
                    args = client.responses.stream.call_args.kwargs
                    assert len(args['tools']) == 9 and args['tool_choice'] == 'none'
                    outputs = [json.loads(i['output']) for i in args['input'] if isinstance(i, dict) and i.get('type') == 'function_call_output']
                    assert outputs[0]['data']['trailingPE'] == 18 and outputs[2]['checks'][0]['period'] == '3mo'
                    assert all(o['chart']['tickers'] == ['XOM'] and o['chart']['days'] == 5 for o in outputs)
                    # Native lookups and dashboard controls share the same four-call budget.
                    extra = [SimpleNamespace(type='function_call', name='set_line_colour', call_id='3',
                                             arguments='{"ticker":"XOM","colour":"green"}'),
                             SimpleNamespace(type='function_call', name='get_fast_info', call_id='4',
                                             arguments='{"ticker":"UNREACHED"}')]
                    first.get_final_response.return_value.output = calls + extra
                    client.responses.stream.side_effect = [nullcontext(first), nullcontext(second)]
                    mixed = await http.post('/api/chat/stream', json=body)
                    mixed_events = [json.loads(line) for line in mixed.text.splitlines()]
                    assert [e['action']['type'] for e in mixed_events if e['type'] == 'action'] == ['set_line_colour']
                    assert any(e.get('message', '').startswith('Four-tool') for e in mixed_events)
                    assert not any(args['ticker'] == 'UNREACHED' for _, args in fake.calls)
                    assert analysis == original and mixed_events[-1] == {'type': 'complete'}
    asyncio.run(checks())
    print('Native MCP chat checks passed.')
