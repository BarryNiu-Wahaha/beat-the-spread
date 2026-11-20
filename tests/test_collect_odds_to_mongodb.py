import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/collect_odds_to_mongodb.py'


class PipelineTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), 'Combined collector not implemented')
        spec = importlib.util.spec_from_file_location('odds_pipeline', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def collection(self):
        collection = MagicMock()
        collection.count_documents.return_value = 2
        collection.update_one.return_value.upserted_id = 'inserted'
        return collection

    def response(self):
        payload = [{'id': 'game-1', 'bookmakers': [{'key': 'draftkings', 'markets': []}]},
                   {'id': 'game-2', 'bookmakers': []}]
        response = MagicMock()
        response.headers = {'x-requests-last': '1', 'x-requests-used': '5',
                            'x-requests-remaining': '495'}
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response
        return response

    def test_database_failure_does_not_spend_api_credit(self):
        module = self.module()
        collection = self.collection()
        collection.database.client.admin.command.side_effect = RuntimeError('secret-uri')
        opener = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            result = module.run_once(collection, 'secret-key', Path(directory), opener)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['request_attempts'], 0)
            opener.assert_not_called()
            self.assertNotIn('secret-uri', (Path(directory) / 'collection_status.json').read_text())

    def test_one_request_keeps_raw_json_and_imports_games_with_quota(self):
        module = self.module()
        collection = self.collection()
        def open_url(request, timeout):
            collection.database.client.admin.command.assert_called_once_with('ping')
            collection.create_index.assert_called_once()
            self.assertIn('regions=us&markets=h2h', request.full_url)
            self.assertNotIn('secret-key', request.full_url)
            self.assertEqual(request.get_header('X-api-key'), 'secret-key')
            return self.response()
        opener = MagicMock(side_effect=open_url)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = module.run_once(collection, 'secret-key', output, opener)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['games'], 2)
            self.assertEqual(result['credits_remaining'], '495')
            self.assertEqual(result['credits_last'], '1')
            self.assertEqual(result['verified_documents'], 2)
            opener.assert_called_once()
            raw = json.loads((output / 'odds_raw.json').read_text())
            self.assertEqual(raw[0]['bookmakers'][0]['key'], 'draftkings')
            inserted = collection.update_one.call_args_list[0].args[1]['$setOnInsert']
            self.assertEqual(inserted['raw'], raw[0])
            self.assertFalse(list(output.glob('*.csv')))
            self.assertNotIn('secret-key', (output / 'collection_status.json').read_text())

    def test_write_failure_preserves_raw_for_offline_retry(self):
        module = self.module()
        collection = self.collection()
        collection.update_one.side_effect = RuntimeError('private error')
        opener = MagicMock(return_value=self.response())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = module.run_once(collection, 'secret-key', output, opener)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['stage'], 'mongodb_import')
            self.assertTrue((output / 'odds_raw.json').exists())
            self.assertEqual(result['credits_last'], '1')
            self.assertEqual(len(module.prepare_documents(output / 'odds_raw.json')), 2)
            opener.assert_called_once()

    def test_http_error_is_not_retried_or_logged_with_secret(self):
        module = self.module()
        error = HTTPError('https://example.invalid', 401, 'secret-key', {}, io.BytesIO())
        opener = MagicMock(side_effect=error)
        with tempfile.TemporaryDirectory() as directory:
            result = module.run_once(self.collection(), 'secret-key', Path(directory), opener)
            self.assertEqual(result['http_status'], 401)
            self.assertEqual(result['status'], 'failed')
            opener.assert_called_once()
            self.assertNotIn('secret-key', (Path(directory) / 'collection_status.json').read_text())


if __name__ == '__main__':
    unittest.main()
