"""Exercise the merged command-line modes without API or database access."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
ODDS = ROOT / 'scripts/collect_odds_to_mongodb.py'
GUARDIAN = ROOT / 'scripts/collect_guardian_to_mongodb.py'


def load_script(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MergedCollectorTests(unittest.TestCase):
    def test_odds_saved_file_dry_run_works_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'odds_raw.json'
            source.write_text('[{"id":"saved-game","bookmakers":[]}]', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-B', str(ODDS), '--import-file', str(source),
                 '--captured-at', '2026-11-18T00:00:00Z', '--dry-run'],
                input='', capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('saved-game', result.stdout)
            self.assertIn('Dry run only', result.stdout)
            self.assertEqual(source.read_text(), '[{"id":"saved-game","bookmakers":[]}]')

    def test_odds_import_writes_saved_documents_without_requesting_api(self):
        module = load_script(ODDS)
        collection = MagicMock()
        collection.update_one.return_value.upserted_id = 'inserted'
        collection.count_documents.return_value = 1
        client = MagicMock()
        client.__enter__.return_value.__getitem__.return_value.__getitem__.return_value = collection
        driver = types.ModuleType('pymongo')
        driver.MongoClient = MagicMock(return_value=client)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'odds_raw.json'
            source.write_text('[{"id":"saved-game","bookmakers":[]}]', encoding='utf-8')
            args = [str(ODDS), '--import-file', str(source), '--captured-at', '2026-11-18T00:00:00Z']
            with patch.object(sys, 'argv', args), patch.dict(sys.modules, {'pymongo': driver}), \
                    patch.dict(module.os.environ, {'MONGODB_URI': 'fixture-uri'}), \
                    patch.object(module.getpass, 'getpass', side_effect=AssertionError('No API key needed')), \
                    patch.object(module.urllib.request, 'build_opener', side_effect=AssertionError('No HTTP')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)
            document = collection.update_one.call_args.args[1]['$setOnInsert']
            self.assertEqual(document['raw'], {'id': 'saved-game', 'bookmakers': []})

    def test_guardian_backfill_plan_is_offline_and_keeps_date_scope(self):
        result = subprocess.run(
            [sys.executable, '-B', str(GUARDIAN), '--backfill', '--plan', '--include-body',
             '--start', '2024-01-30', '--end', '2024-03-01', '--max-requests', '3'],
            input='', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['month_windows'], 3)
        self.assertEqual(plan['max_requests_this_run'], 3)
        self.assertEqual(plan['query_example']['show-fields'], 'bodyText')

    def test_guardian_backfill_writes_local_outputs_without_mongodb(self):
        module = load_script(GUARDIAN)
        payload = {'response': {'status': 'ok', 'currentPage': 1, 'pages': 1, 'total': 1,
                   'results': [{'id': 'one', 'webPublicationDate': '2024-02-12T00:00:00Z',
                                'fields': {'bodyText': 'Saved article body'}}]}}
        with tempfile.TemporaryDirectory() as folder:
            args = [str(GUARDIAN), '--backfill', '--include-body', '--start', '2024-02-01',
                    '--end', '2024-02-29', '--max-requests', '1']
            with patch.object(sys, 'argv', args), patch.object(module, 'ROOT', Path(folder)), \
                    patch.dict(sys.modules, {'pymongo': None}), \
                    patch.dict(module.os.environ, {'GUARDIAN_API_KEY': 'fixture-key'}), \
                    patch.object(module, 'make_fetcher', return_value=lambda params: payload), \
                    patch.object(module.getpass, 'getpass', side_effect=AssertionError('No MongoDB needed')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)
            output = Path(folder) / 'data/collected/guardian_2024-02-01_2024-02-29_body'
            article = json.loads((output / 'news.jsonl').read_text())
            self.assertEqual(article['body_text'], 'Saved article body')
            self.assertTrue((output / 'pages/2024-02-01_2024-02-29_page_00001.json').is_file())

    def test_conflicting_modes_fail_before_credentials_or_network(self):
        cases = [(ODDS, ['--dry-run']),
                 (ODDS, ['--check-connection', '--import-file', 'unused.json']),
                 (GUARDIAN, ['--backfill', '--resume', 'unused']),
                 (GUARDIAN, ['--backfill', '--page', '2']),
                 (GUARDIAN, ['--include-body'])]
        for script, flags in cases:
            with self.subTest(script=script.name, flags=flags):
                result = subprocess.run([sys.executable, '-B', str(script), *flags],
                                        input='', capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == '__main__':
    unittest.main()
