import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/collect_odds_to_mongodb.py'


class MongoImportTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), 'MongoDB importer not implemented')
        spec = importlib.util.spec_from_file_location('mongo_import', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_preserves_nested_games_and_stable_snapshot_ids(self):
        module = self.module()
        games = [{'id': 'game-1', 'bookmakers': [{'key': 'fixture', 'markets': []}]},
                 {'id': 'game-2', 'bookmakers': []}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'odds_raw.json'
            path.write_text(json.dumps(games), encoding='utf-8-sig')
            before = path.read_bytes()
            docs = module.prepare_documents(path, '2026-11-18T00:22:10Z')
            self.assertEqual(len(docs), 2)
            self.assertEqual([doc['raw'] for doc in docs], games)
            self.assertEqual(len({doc['_id'] for doc in docs}), 2)
            again = module.prepare_documents(path, '2026-11-18T00:22:10Z')
            self.assertEqual([d['_id'] for d in docs], [d['_id'] for d in again])
            later = module.prepare_documents(path, '2026-11-19T00:22:10Z')
            self.assertNotEqual(docs[0]['_id'], later[0]['_id'])
            self.assertEqual(path.read_bytes(), before)

    def test_uses_companion_metadata_and_requires_timestamp(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'odds_raw.json'
            path.write_text('[{"id":"game-1"}]', encoding='utf-8')
            with self.assertRaises(ValueError):
                module.prepare_documents(path)
            (path.parent / 'collection_status.json').write_text(json.dumps({
                'attempted_at_utc': '2026-11-18T00:22:10Z'}), encoding='utf-8-sig')
            docs = module.prepare_documents(path)
            self.assertEqual(docs[0]['snapshot_time_basis'], 'request_started')
            with self.assertRaises(ValueError):
                module.prepare_documents(path, '2026-11-18T00:22:10')

    def test_rejects_duplicate_game_ids_before_any_writes(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'odds_raw.json'
            path.write_text('[{"id":"same"},{"id":"same"}]', encoding='utf-8')
            with self.assertRaises(ValueError):
                module.prepare_documents(path, '2026-11-18T00:22:10Z')

    def test_repeat_import_does_not_insert_duplicates(self):
        module = self.module()
        class Collection:
            def __init__(self):
                self.docs = {}

            def update_one(self, query, update, upsert):
                self.assert_valid(query, update, upsert)
                key = query['_id']
                inserted = key not in self.docs
                if inserted:
                    self.docs[key] = update['$setOnInsert']
                return type('Result', (), {'upserted_id': key if inserted else None})()

            def assert_valid(self, query, update, upsert):
                assert upsert is True
                assert set(update) == {'$setOnInsert'}
                assert query['_id'] == update['$setOnInsert']['_id']

        collection = Collection()
        docs = [{'_id': 'snapshot-1', 'raw': {'id': 'game-1'}}]
        self.assertEqual(module.import_documents(collection, docs), {'inserted': 1, 'already_present': 0})
        self.assertEqual(module.import_documents(collection, docs), {'inserted': 0, 'already_present': 1})


if __name__ == '__main__':
    unittest.main()
