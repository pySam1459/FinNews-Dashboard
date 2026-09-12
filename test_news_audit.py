"""Headline shortlist contract and cache checks; no network or API credits."""
from types import SimpleNamespace
from unittest.mock import patch
import news_dashboard as d

def run():
    candidates = [{'id': 'oil', 'title': 'Supply disruption', 'published': '2026-09-12T10:00:00Z',
                   'summary': 'A major pipeline closes.'},
                  {'id': 'tips', 'title': 'Shopping tips', 'published': '2026-09-12T11:00:00Z', 'summary': 'Tips.'}]
    with patch.dict(d.os.environ, {'OAI_KEY': 'test-only'}), patch.object(d, 'OpenAI') as sdk:
        client = sdk.return_value.__enter__.return_value
        client.responses.parse.return_value = SimpleNamespace(output_parsed=d.FeedAudit(selections=[
            d.FeedPick(id='oil', reason='Potential oil supply shock.'), d.FeedPick(id='oil', reason='Duplicate')]))
        selected = d.audit_headlines(candidates)
        assert [s['id'] for s in selected] == ['oil']
        assert selected[0]['marketReason'] == 'Potential oil supply shock.'
        client.responses.parse.return_value.output_parsed = d.FeedAudit(selections=[d.FeedPick(id='invented', reason='Bad')])
        try:
            d.audit_headlines(candidates)
            raise AssertionError('Unknown ID accepted')
        except ValueError:
            pass
        client.responses.parse.return_value.output_parsed = d.FeedAudit(selections=[])
        assert d.audit_headlines(candidates) == []
    class Entry(dict):
        __getattr__ = dict.__getitem__
    entry = Entry(title='Supply disruption', link='https://www.bbc.com/news/test',
                  summary='A pipeline closes.', published_parsed=(2026, 9, 12, 10, 0, 0, 5, 255, 0))
    state = {k: getattr(d, k) for k in ('feed_time', 'feed_result', 'feed_fingerprint', 'feed_warnings', 'stories')}
    try:
        d.feed_time, d.feed_result, d.feed_fingerprint, d.feed_warnings, d.stories = 0, None, None, [], {}
        with patch.object(d, 'public_get', return_value=b'feed'), patch.object(d.feedparser, 'parse', return_value=SimpleNamespace(entries=[entry])), patch.object(d, 'audit_headlines', return_value=selected) as audit:
            first = d.news()
            assert first['audited'] and first['stories'] == selected
            d.news()
            d.feed_time = 0
            d.news()
            assert audit.call_count == 1, 'Unchanged batches must not spend credits again'
            entry['title'] = 'New headline'
            audit.side_effect = ValueError('Screen failed')
            d.feed_time = 0
            failed = d.news()
            assert failed['stories'] == selected and failed['warnings']
            d.news()
            assert audit.call_count == 2, 'Failed audits must be throttled'
            d.feed_result = None
            try:
                d.news()
                raise AssertionError('Unaudited feed exposed')
            except d.HTTPException as exc:
                assert exc.status_code == 503
    finally:
        for key, value in state.items():
            setattr(d, key, value)
    print('Headline audit checks passed.')
