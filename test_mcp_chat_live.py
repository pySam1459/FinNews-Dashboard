"""Live chat-to-MCP check. Uses OpenAI credits and a synthetic cached story."""
import asyncio
import json
from copy import deepcopy
from unittest.mock import patch

import httpx
import market_mcp
import news_dashboard as d


def run():
    async def check():
        story = {'id': 'mcp-check', 'title': 'Synthetic MCP integration fixture',
                 'summary': 'Test fixture, not a live news article.', 'publisher': 'Test fixture',
                 'published': '2026-10-03T10:00:00Z', 'url': 'https://www.bbc.com/news/test'}
        analysis = {'summary': 'Synthetic context for verifying read-only market research.',
                    'securities': [{'ticker': 'XOM', 'name': 'Exxon Mobil', 'reason': 'Fixture', 'direction': 'uncertain'}],
                    'events': [], 'coverage': 'Synthetic fixture', 'mcpChecks': []}
        original = deepcopy(analysis)
        body = {'id': story['id'], 'days': 5, 'rangeStart': '', 'rangeEnd': '', 'prices': [],
                'messages': [{'role': 'user', 'content':
                    "Check BP's latest quote, curated fundamentals and price change over the last three months using OpenMarkets. Leave the dashboard unchanged."}]}
        async with market_mcp.lifespan(d.app):
            assert set(market_mcp.chat_tools) == set(market_mcp.TOOLS), 'Native MCP tools were not discovered'
            with patch.object(d, 'stories', {story['id']: story}), patch.object(d, 'analyses', {story['id']: analysis}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=d.app), base_url='http://localhost') as http:
                    response = await http.post('/api/chat/stream', json=body)
                    response.raise_for_status()
                    events = [json.loads(line) for line in response.text.splitlines()]
                    for event in events:
                        if event['type'] in ('tool', 'error'):
                            print(json.dumps({k: event[k] for k in ('type', 'tool', 'status', 'message') if k in event}), flush=True)
                    assert events[-1]['type'] == 'complete', 'Chat did not finish'
                    completed = {e['tool'] for e in events if e['type'] == 'tool' and e['status'] == 'completed'}
                    assert set(market_mcp.TOOLS) <= completed, 'Luna did not successfully use all three requested native tools'
                    assert not any(e['type'] == 'action' for e in events), 'Read-only research changed the dashboard'
                    assert analysis == original, 'Read-only research changed the shared analysis'
                    assert any(c.get('period') == '3mo' and c.get('interval') == '1d'
                               for e in events for c in e.get('checks', [])), 'Requested history range was not forwarded'
                    print(''.join(e['text'] for e in events if e['type'] == 'delta').strip(), flush=True)
                    print('Live native MCP chat check passed.', flush=True)
    asyncio.run(check())
