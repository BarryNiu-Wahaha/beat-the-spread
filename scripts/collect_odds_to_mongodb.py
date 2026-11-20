"""Collect one NBA odds snapshot into MongoDB, or import a saved snapshot.

Collect once: python scripts/collect_odds_to_mongodb.py
Preview saved JSON: python scripts/collect_odds_to_mongodb.py --import-file FILE --dry-run
Import saved JSON: python scripts/collect_odds_to_mongodb.py --import-file FILE
Check Atlas only: python scripts/collect_odds_to_mongodb.py --check-connection

Use MONGODB_URI and ODDS_API_KEY environment variables or hidden prompts.
Saved-file imports never request Odds or need an Odds API key. No scheduler,
CSV conversion, or automatic Odds API retries. Install pymongo for cloud modes.
"""

import argparse
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://api.the-odds-api.com/v4/sports/basketball_nba/odds'
QUOTA_HEADERS = {'credits_last': 'x-requests-last', 'credits_used': 'x-requests-used',
                 'credits_remaining': 'x-requests-remaining'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Avoid additional HTTP requests or forwarding the API key to another host."""
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def prepare_documents(json_file, captured_at=None):
    """Validate the entire file before writing; keep original objects under raw."""
    json_file = Path(json_file)
    content = json_file.read_bytes()
    games = json.loads(content.decode('utf-8-sig'))
    if not isinstance(games, list):
        raise ValueError('Expected a JSON array of game objects: [{...}, {...}]')

    time_basis = 'explicit'
    if not captured_at:
        status_path = json_file.parent / 'collection_status.json'
        if not status_path.is_file():
            raise ValueError('Supply --captured-at or keep collection_status.json beside the JSON')
        status = json.loads(status_path.read_text(encoding='utf-8-sig'))
        captured_at = status.get('retrieved_at_utc') or status.get('attempted_at_utc')
        time_basis = 'retrieved' if status.get('retrieved_at_utc') else 'request_started'
    if not isinstance(captured_at, str):
        raise ValueError('Missing snapshot timestamp; supply --captured-at')
    snapshot_time = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
    if snapshot_time.tzinfo is None:
        raise ValueError('Snapshot timestamp must include a timezone, e.g. 2026-11-18T00:22:10Z')
    snapshot_time = snapshot_time.astimezone(timezone.utc)
    # BSON dates store milliseconds. Normalize before constructing the stable ID.
    snapshot_time = snapshot_time.replace(microsecond=(snapshot_time.microsecond // 1000) * 1000)
    source_hash = hashlib.sha256(content).hexdigest()
    documents = []
    seen = set()
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get('id'), str) or not game['id']:
            raise ValueError('Every game must be an object with a nonempty string id')
        if game['id'] in seen:
            raise ValueError('Duplicate event ID in source JSON')
        seen.add(game['id'])
        identity = json.dumps([source_hash, snapshot_time.isoformat(), game['id']])
        documents.append({
            '_id': hashlib.sha256(identity.encode('utf-8')).hexdigest(),
            'source': 'the_odds_api',
            'event_id': game['id'],
            'snapshot_at_utc': snapshot_time,
            'snapshot_time_basis': time_basis,
            'source_file': json_file.name,
            'source_sha256': source_hash,
            'raw': game,
        })
    return documents


def import_documents(collection, documents):
    """Insert absent snapshots; leave snapshots already imported unchanged."""
    inserted = 0
    for document in documents:
        result = collection.update_one(
            {'_id': document['_id']}, {'$setOnInsert': document}, upsert=True)
        if result.upserted_id is not None:
            inserted += 1
    return {'inserted': inserted, 'already_present': len(documents) - inserted}


def save_status(output, report):
    temporary = output / 'collection_status.json.tmp'
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output / 'collection_status.json')


def check_connection(collection):
    collection.database.client.admin.command('ping')
    collection.create_index([('event_id', 1), ('snapshot_at_utc', -1)])


def run_once(collection, api_key, output, open_url=None):
    """Save the raw response before import; make at most one Odds HTTP request."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'collection_status.json').exists() or (output / 'odds_raw.json').exists():
        raise ValueError('Use a new output folder; existing snapshots are never overwritten')
    now = datetime.now(timezone.utc)
    params = {'regions': 'us', 'markets': 'h2h', 'oddsFormat': 'decimal', 'dateFormat': 'iso',
              'commenceTimeTo': (now + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    report = {'source': 'The Odds API', 'endpoint': ENDPOINT, 'parameters': params,
              'status': 'pending', 'stage': 'mongodb_preflight', 'request_attempts': 0,
              'automatic_retries': 0, 'expected_credits': 1,
              'credits_last': None, 'credits_used': None, 'credits_remaining': None}
    save_status(output, report)
    try:
        check_connection(collection)
        if not api_key.strip():
            raise ValueError('Missing API key')
        request = urllib.request.Request(ENDPOINT + '?' + urllib.parse.urlencode(params),
            headers={'x-api-key': api_key, 'Accept': 'application/json',
                     'User-Agent': 'NBA-course-research/1.0'})
        report.update(stage='odds_request', request_attempts=1,
                      attempted_at_utc=datetime.now(timezone.utc).isoformat())
        save_status(output, report)
        if open_url is None:
            open_url = urllib.request.build_opener(NoRedirect()).open
        with open_url(request, timeout=25) as response:
            report.update({field: response.headers.get(header) for field, header in QUOTA_HEADERS.items()})
            save_status(output, report)
            payload = response.read(20_000_001)
        if len(payload) > 20_000_000:
            raise ValueError('Response exceeds the 20 MB limit')
        report.update(stage='save_raw', retrieved_at_utc=datetime.now(timezone.utc).isoformat())
        with (output / 'odds_raw.json').open('xb') as stream:
            stream.write(payload)
        save_status(output, report)
        report['stage'] = 'validate_json'
        documents = prepare_documents(output / 'odds_raw.json')
        report.update(games=len(documents), stage='mongodb_import')
        save_status(output, report)
        report.update(import_documents(collection, documents))
        ids = [document['_id'] for document in documents]
        verified = collection.count_documents({'_id': {'$in': ids}}) if ids else 0
        if verified != len(documents):
            raise RuntimeError('MongoDB document count does not match the snapshot')
        report.update(status='completed', stage='done', verified_documents=verified)
    except urllib.error.HTTPError as error:
        report.update(status='failed', http_status=error.code, error_type=type(error).__name__)
        report.update({field: error.headers.get(header) for field, header in QUOTA_HEADERS.items()})
    except Exception as error:
        # Driver and HTTP error strings can contain credentials; report only their type.
        report.update(status='failed', error_type=type(error).__name__)
    finally:
        save_status(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='nba_project')
    parser.add_argument('--collection', default='odds_snapshots')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check-connection', action='store_true',
                       help='Check MongoDB and create the query index; never call Odds API')
    modes.add_argument('--import-file', type=Path,
                       help='Import a saved odds JSON file without another Odds request')
    parser.add_argument('--captured-at', help='Override saved snapshot time; must include timezone')
    parser.add_argument('--dry-run', action='store_true', help='Preview --import-file locally')
    args = parser.parse_args()
    if (args.dry_run or args.captured_at is not None) and args.import_file is None:
        parser.error('--dry-run and --captured-at require --import-file')

    # Validate saved input before loading the driver or asking for credentials.
    if args.import_file is not None:
        try:
            documents = prepare_documents(args.import_file, args.captured_at)
        except (OSError, ValueError) as error:
            print(f'Input validation failed: {error}', file=sys.stderr)
            return 1
        print(f'Documents: {len(documents)}; target: {args.database}.{args.collection}')
        if args.dry_run:
            if documents:
                print(json.dumps(documents[0], indent=2, ensure_ascii=False, default=str))
            print('Dry run only: no MongoDB connection and no Odds API request.')
            return 0
        if not documents:
            print('Empty source: nothing to import.')
            return 0

    try:
        from pymongo import MongoClient
    except ImportError:
        print('Install the driver: python -m pip install pymongo', file=sys.stderr)
        return 1
    uri = os.environ.get('MONGODB_URI', '').strip() or getpass.getpass('MongoDB connection URI (hidden): ')
    if not uri:
        print('MongoDB URI is required.', file=sys.stderr)
        return 1
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000,
                         socketTimeoutMS=30000) as client:
            collection = client[args.database][args.collection]
            if args.check_connection:
                check_connection(collection)
                print(f'MongoDB connected; index ready: {args.database}.{args.collection}')
                print('No Odds API request made.')
                return 0
            if args.import_file is not None:
                check_connection(collection)
                result = import_documents(collection, documents)
                verified = collection.count_documents({'_id': {'$in': [d['_id'] for d in documents]}})
                if verified != len(documents):
                    raise RuntimeError('Stored document count does not match the input')
                print(json.dumps({**result, 'verified_documents': verified}))
                return 0

            key = os.environ.get('ODDS_API_KEY', '').strip() or getpass.getpass('Odds API key (hidden): ')
            if not key:
                print('Odds API key is required.', file=sys.stderr)
                return 1
            batch = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
            output = ROOT / 'data/collected' / ('odds_mongodb_' + batch)
            report = run_once(collection, key, output)
            print(json.dumps(report, indent=2))
            print('Local backup: ' + str(output))
            if report['status'] != 'completed':
                if report['stage'] == 'mongodb_preflight':
                    print('Check Atlas user permissions, IP access list and URI. No Odds request made.')
                elif (output / 'odds_raw.json').exists():
                    print('Raw JSON saved. Rerun this script with --import-file PATH_TO_JSON '
                          'to retry the import without another Odds request.')
                else:
                    print('No usable snapshot saved. Check the recorded failure and quota before rerunning.')
                return 1
    except Exception as error:
        print(f'Unable to complete operation ({type(error).__name__}). '
              'Check the saved status, MongoDB URI, permissions and network. '
              'For a partial saved-file import, rerun with --import-file.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
