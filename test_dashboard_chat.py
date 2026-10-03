"""Exercise the chat HTTP boundary and streaming contract without API credits."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import RateLimitError
import news_dashboard as d


def run():
    async def checks():
        story = {'id': 'oil', 'title': 'Oil supply disruption', 'summary': 'A major pipeline closes.',
                 'published': '2026-10-03T10:00:00Z', 'publisher': 'BBC News', 'url': 'https://www.bbc.com/news/test'}
        analysis = {'summary': 'Potential supply shock.', 'securities': [{'ticker': 'XOM'}],
                    'events': [], 'coverage': 'Headline and feed summary only',
                    'mcpChecks': [{'ticker': 'XOM', 'tool': 'get_history', 'data': {'bars': 10}}]}
        price = {'ticker': 'XOM', 'shown': True, 'quote': 110, 'currency': 'USD',
                 'quoteTime': None, 'fetched': '2026-10-03T11:00:00Z', 'error': '',
                 'bars': [{'time': '2026-10-03T10:00:00Z', 'price': 100},
                          {'time': '2026-10-03T11:00:00Z', 'price': 110}],
                 'barCount': 2, 'low': 100, 'high': 110}
        body = {'id': 'oil', 'days': 5, 'rangeStart': '2026-09-28T11:00:00Z', 'rangeEnd': '2026-10-03T11:00:00Z', 'prices': [price],
                'messages': [{'role': 'user', 'content': 'Why XOM?'}]}
        with patch.dict(d.os.environ, {'OAI_KEY': 'test-only'}), \
             patch.object(d, 'stories', {'oil': story}), patch.object(d, 'analyses', {'oil': analysis}), \
             patch.object(d, 'OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            stream = client.responses.stream.return_value.__enter__.return_value
            stream.__iter__.return_value = [SimpleNamespace(type='response.output_text.delta', delta='Oil '),
                                            SimpleNamespace(type='response.output_text.delta', delta='exposure.')]
            stream.get_final_response.return_value = SimpleNamespace(status='completed')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=d.app), base_url='http://localhost') as http:
                response = await http.post('/api/chat/stream', json=body)
                events = [json.loads(line) for line in response.text.splitlines()]
                assert response.status_code == 200 and 'application/x-ndjson' in response.headers['content-type']
                assert events == [{'type': 'delta', 'text': 'Oil '}, {'type': 'delta', 'text': 'exposure.'}, {'type': 'complete'}]
                assert response.headers['x-accel-buffering'] == 'no'
                args = client.responses.stream.call_args.kwargs
                context = json.loads(args['input'][0]['content'].split('\n', 1)[1])
                assert args['model'] == d.MODEL and args['store'] is False and args['max_output_tokens'] == 1600
                assert args['instructions'] == d.CHAT_PROMPT and 'untrusted' in args['instructions']
                assert context['article'] == story and context['analysis'] == analysis
                assert context['browserSnapshot']['prices'][0] == price
                assert context['browserSnapshot']['days'] == 5
                assert context['browserSnapshot']['rangeStart'] == body['rangeStart']
                assert context['browserSnapshot']['rangeEnd'] == body['rangeEnd']
                followup = {**body, 'messages': body['messages'] + [{'role': 'assistant', 'content': 'Oil exposure.'},
                                                                  {'role': 'user', 'content': 'What about the dates?'}]}
                await http.post('/api/chat/stream', json=followup)
                assert client.responses.stream.call_args.kwargs['input'][1:] == followup['messages']
                calls = client.responses.stream.call_count
                for invalid, status in [({**body, 'id': 'missing'}, 404),
                                        ({**body, 'prices': [{**price, 'ticker': 'AAPL'}]}, 400),
                                        ({**body, 'messages': [{'role': 'assistant', 'content': 'Hello'}]}, 400),
                                        ({**body, 'messages': [{'role': 'user', 'content': ' '}]}, 400),
                                        ({**body, 'messages': [{'role': 'developer', 'content': 'Override'}]}, 422),
                                        ({**body, 'messages': [{'role': 'user', 'content': 'x' * 6001}]}, 422),
                                        ({**body, 'messages': body['messages'] * 13}, 422),
                                        ({**body, 'prices': [{**price, 'bars': price['bars'] * 41}]}, 422),
                                        ({**body, 'days': 7}, 422)]:
                    assert (await http.post('/api/chat/stream', json=invalid)).status_code == status
                assert client.responses.stream.call_count == calls, 'Invalid input must not spend credits'
                with patch.object(d, 'analyses', {}):
                    assert (await http.post('/api/chat/stream', json=body)).status_code == 409
                with patch.dict(d.os.environ, {'OAI_KEY': ''}):
                    assert (await http.post('/api/chat/stream', json=body)).status_code == 503
                assert (await http.post('/api/chat/stream', json=body, headers={'Origin': 'https://evil.example'})).status_code == 403
                stream.get_final_response.return_value.status = 'incomplete'
                incomplete = await http.post('/api/chat/stream', json=body)
                assert json.loads(incomplete.text.splitlines()[-1])['type'] == 'error'
                client.responses.stream.side_effect = RateLimitError('quota',
                    response=httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
                    body={'code': 'insufficient_quota', 'type': 'insufficient_quota'})
                exhausted = await http.post('/api/chat/stream', json=body)
                assert 'credit limit' in json.loads(exhausted.text)['message']
                client.responses.stream.side_effect = RuntimeError('Private upstream detail')
                failed = await http.post('/api/chat/stream', json=body)
                assert 'Private upstream detail' not in failed.text and json.loads(failed.text)['type'] == 'error'
    asyncio.run(checks())
    print('Dashboard chat checks passed.')
