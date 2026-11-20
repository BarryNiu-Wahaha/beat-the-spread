import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/collect_guardian_to_mongodb.py'


def article(identifier, published='2024-02-29T23:00:00Z'):
    return {'id': identifier, 'webPublicationDate': published,
            'webTitle': 'Fixture headline', 'webUrl': 'https://example.org/' + identifier,
            'type': 'article', 'tags': [{'id': 'sport/nba'}]}


def page(number, results, pages=2, total=2):
    return {'response': {'status': 'ok', 'currentPage': number, 'pages': pages,
                         'total': total, 'results': results}}


class BackfillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location('collector', SCRIPT)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        else:
            cls.module = None

    def collector(self):
        self.assertIsNotNone(self.module, 'Date-range collector has not been implemented')
        return self.module

    def test_months_include_partial_bounds_and_leap_day(self):
        module = self.collector()
        self.assertEqual(module.month_windows('2024-01-30', '2024-03-01'), [
            ('2024-01-30', '2024-01-31'), ('2024-02-01', '2024-02-29'),
            ('2024-03-01', '2024-03-01')])
        with self.assertRaises(ValueError):
            module.month_windows('2024-03-01', '2024-01-01')

    def test_request_dates_and_body_are_explicit(self):
        module = self.collector()
        params = module.query_params('2024-02-01', '2024-02-29', 2, False)
        self.assertEqual(params['from-date'], '2024-02-01')
        self.assertEqual(params['to-date'], '2024-02-29')
        self.assertEqual(params['tag'], 'sport/nba')
        self.assertEqual(params['page'], 2)
        self.assertNotIn('bodyText', params.get('show-fields', ''))
        self.assertIn('bodyText', module.query_params('2024-02-01', '2024-02-29', 1, True)['show-fields'])

    def test_budget_resume_uses_saved_pages(self):
        module = self.collector()
        calls = []
        def fetch(params):
            calls.append(params['page'])
            return page(params['page'], [article(str(params['page']))])
        with tempfile.TemporaryDirectory() as directory:
            first = module.collect('2024-02-01', '2024-02-29', Path(directory), fetch, 1)
            self.assertEqual(first['status'], 'request_budget_reached')
            self.assertEqual(first['records'], 1)
            second = module.collect('2024-02-01', '2024-02-29', Path(directory), fetch, 1)
            self.assertEqual(second['status'], 'query_pages_fetched')
            self.assertEqual(second['records'], 2)
            self.assertEqual(calls, [1, 2])
            rows = [json.loads(line) for line in (Path(directory) / 'news.jsonl').read_text().splitlines()]
            self.assertEqual(len({row['source_id'] for row in rows}), 2)

    def test_duplicate_pages_do_not_claim_complete_coverage(self):
        module = self.collector()
        with tempfile.TemporaryDirectory() as directory:
            result = module.collect('2024-02-01', '2024-02-29', Path(directory),
                                    lambda params: page(params['page'], [article('same')]), 10)
            self.assertEqual(result['records'], 1)
            self.assertEqual(result['status'], 'needs_review')

    def test_failure_is_reported_and_not_cached_as_success(self):
        module = self.collector()
        def fail(params):
            raise RuntimeError('Network unavailable')
        with tempfile.TemporaryDirectory() as directory:
            result = module.collect('2024-02-01', '2024-02-29', Path(directory), fail, 10)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['records'], 0)
            self.assertFalse(list((Path(directory) / 'pages').glob('*.json')))
            self.assertTrue((Path(directory) / 'coverage.json').exists())

    def test_unknown_and_outside_dates_are_not_silently_accepted(self):
        module = self.collector()
        data = [article('old', '2023-01-01T00:00:00Z'), article('missing', ''),
                article('good'), article('invalid', '2024-02-30T00:00:00Z')]
        with tempfile.TemporaryDirectory() as directory:
            result = module.collect('2024-02-01', '2024-02-29', Path(directory),
                                    lambda params: page(1, data, 1, 4), 10)
            self.assertEqual(result['records'], 1)
            self.assertEqual(result['excluded_outside_range'], 1)
            self.assertEqual(result['unknown_publication_date'], 2)
            self.assertEqual(result['status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
