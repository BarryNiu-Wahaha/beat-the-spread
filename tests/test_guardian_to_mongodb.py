import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/collect_guardian_to_mongodb.py'


def payload():
    return {'response': {'status': 'ok', 'currentPage': 1, 'pages': 1, 'total': 2,
        'results': [
            {'id': 'sport/example-one', 'webTitle': 'Fixture article',
             'webPublicationDate': '2026-11-17T12:00:00Z', 'webUrl': 'https://example.org/one',
             'fields': {'bodyText': 'Fixture full text.', 'byline': 'Fixture author'},
             'tags': [{'id': 'sport/nba'}]},
            {'id': 'sport/example-two', 'webTitle': 'No body supplied',
             'webPublicationDate': '2026-11-17T13:00:00Z', 'webUrl': 'https://example.org/two'}]}}


class GuardianMongoTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), 'Guardian MongoDB collector not implemented')
        spec = importlib.util.spec_from_file_location('guardian_mongo', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def collection(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.update_one.return_value.upserted_id = 'inserted'
        collection.count_documents.return_value = 2
        return collection

    def test_preflight_failure_never_calls_news_api(self):
        module = self.module()
        collection = self.collection()
        collection.database.client.admin.command.side_effect = RuntimeError('private URI')
        fetch = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            result = module.run_once(collection, Path(directory), {'page': 1}, fetch)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['request_attempts'], 0)
            fetch.assert_not_called()
            self.assertNotIn('private URI', (Path(directory) / 'collection_status.json').read_text())

    def test_one_request_saves_body_and_flags_missing_body(self):
        module = self.module()
        collection = self.collection()
        def fetch(params):
            collection.database.client.admin.command.assert_called_once_with('ping')
            self.assertEqual(params['page-size'], 10)
            self.assertIn('bodyText', params['show-fields'])
            return payload()
        request = MagicMock(side_effect=fetch)
        with tempfile.TemporaryDirectory() as directory:
            result = module.run_once(collection, Path(directory), module.news_params('2023-11-17', '2026-11-17'), request)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['articles'], 2)
            self.assertEqual(result['articles_with_body'], 1)
            self.assertEqual(result['verified_documents'], 2)
            request.assert_called_once()
            docs = [call.args[1]['$set'] for call in collection.update_one.call_args_list]
            self.assertEqual(docs[0]['body_text'], 'Fixture full text.')
            self.assertTrue(docs[0]['rag_ready'])
            self.assertFalse(docs[1]['rag_ready'])
            self.assertFalse(list(Path(directory).glob('*.csv')))

    def test_failed_import_can_resume_without_request_and_keeps_ids(self):
        module = self.module()
        collection = self.collection()
        collection.update_one.side_effect = RuntimeError('private failure')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            fetch = MagicMock(return_value=payload())
            first = module.run_once(collection, folder, {'page': 1}, fetch)
            self.assertEqual(first['status'], 'failed')
            self.assertTrue((folder / 'guardian_raw.json').is_file())
            original = json.loads((folder / 'guardian_raw.json').read_text())
            collection = self.collection()
            never = MagicMock(side_effect=AssertionError('Resume must not call API'))
            second = module.run_once(collection, folder, None, never, resume=True)
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(second['request_attempts'], 0)
            never.assert_not_called()
            self.assertEqual(json.loads((folder / 'guardian_raw.json').read_text()), original)
            self.assertEqual(collection.update_one.call_args_list[0].args[0], {'_id': 'guardian:sport/example-one'})

    def test_duplicate_article_ids_are_rejected_before_import(self):
        module = self.module()
        data = payload()
        data['response']['results'][1]['id'] = data['response']['results'][0]['id']
        with self.assertRaises(ValueError):
            module.prepare_news(data, '2026-11-17T14:00:00Z')

    def test_older_saved_page_does_not_replace_newer_article(self):
        module = self.module()
        docs = module.prepare_news(payload(), '2026-11-17T14:00:00Z')
        collection = self.collection()
        collection.find_one.return_value = {'retrieved_at_utc': docs[0]['retrieved_at_utc']}
        result = module.store_news(collection, docs)
        self.assertEqual(result['already_current'], 2)
        collection.update_one.assert_not_called()


if __name__ == '__main__':
    unittest.main()
