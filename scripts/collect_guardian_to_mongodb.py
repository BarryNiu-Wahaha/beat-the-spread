"""Collect Guardian NBA news into MongoDB, or backfill to local files.

Default: one page with article bodies, backed up locally and stored in MongoDB.
--resume BATCH: import an existing guardian_raw.json batch without a new request.
--check-connection: check Atlas and create the query index only.
--backfill: monthly paginated local JSON/CSV, with a default 100-request budget.
--backfill --plan: preview scope offline; --include-body adds backfill body text.

Use MONGODB_URI and GUARDIAN_API_KEY environment variables or hidden prompts.
Local backfill requires GUARDIAN_API_KEY in the environment and never uses MongoDB.
Run one instance at a time. No S3, embeddings or automatic retries.
"""

import argparse
import calendar
import csv
from datetime import date, datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


ENDPOINT = 'https://content.guardianapis.com/search'
FIELDS = ['source', 'source_id', 'url', 'title', 'published_at_utc',
          'retrieved_at_utc', 'content_type', 'tags', 'body_text']


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def month_windows(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError('Start must not be after end')
    windows = []
    while first <= last:
        month_end = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        windows.append((first.isoformat(), min(month_end, last).isoformat()))
        if month_end >= last:
            break
        first = date.fromordinal(month_end.toordinal() + 1)
    return windows


def query_params(start, end, page, include_body):
    params = {'tag': 'sport/nba', 'from-date': start, 'to-date': end,
              'order-by': 'oldest', 'page-size': 50, 'page': page,
              'show-tags': 'keyword', 'use-date': 'published'}
    if include_body:
        params['show-fields'] = 'bodyText'
    return params


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def validate_page(payload, number):
    response = payload.get('response', {})
    if response.get('status') != 'ok' or response.get('currentPage') != number:
        raise ValueError('API did not return the requested successful page')
    for field in ('pages', 'total'):
        if not isinstance(response.get(field), int) or response[field] < 0:
            raise ValueError('Missing or invalid pagination metadata')
    if not isinstance(response.get('results'), list):
        raise ValueError('Missing results list')
    if response['total'] > 0 and response['pages'] < number:
        raise ValueError('Page count contradicts result total')
    for item in response['results']:
        if not isinstance(item, dict) or not item.get('id'):
            raise ValueError('Article has no source ID')
    return response


def collect(start, end, output, fetch, max_requests=100, include_body=False):
    """fetch(params) returns API JSON. Cache only validated, completed pages."""
    windows = month_windows(start, end)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / 'pages'
    cache.mkdir(exist_ok=True)
    config = {'source': ENDPOINT, 'start': start, 'end': end,
              'include_body': include_body, 'tag': 'sport/nba', 'page_size': 50,
              'schema_version': 1}
    config_path = output / 'query.json'
    if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8')) != config:
        raise ValueError('Output directory belongs to a different query; use another directory')
    write_json(config_path, config)
    report = {**config, 'updated_at_utc': utc_now(), 'status': 'query_pages_fetched',
              'requests_this_run': 0, 'records': 0, 'excluded_outside_range': 0,
              'unknown_publication_date': 0, 'months': [], 'errors': [],
              'coverage_note': 'Only this source and NBA tag. Counts are not proof of all NBA news. '
                               'Cached pages are a backfill snapshot, not a live synchronization.'}
    rows = {}
    needs_review = False
    for month_start, month_end in windows:
        month = {'start': month_start, 'end': month_end, 'pages_saved': 0,
                 'reported_total': None, 'unique_ids': 0, 'status': 'pending'}
        report['months'].append(month)
        ids = set()
        page_number = 1
        totals = set()
        expected_pages = set()
        try:
            while True:
                path = cache / f'{month_start}_{month_end}_page_{page_number:05d}.json'
                if path.exists():
                    saved = json.loads(path.read_text(encoding='utf-8'))
                else:
                    if report['requests_this_run'] >= max_requests:
                        report['status'] = 'request_budget_reached'
                        month['status'] = 'partial'
                        break
                    report['requests_this_run'] += 1
                    payload = fetch(query_params(month_start, month_end, page_number, include_body))
                    validate_page(payload, page_number)
                    saved = {'retrieved_at_utc': utc_now(), 'payload': payload}
                    write_json(path, saved)
                response = validate_page(saved['payload'], page_number)
                month['pages_saved'] += 1
                month['reported_total'] = response['total']
                totals.add(response['total'])
                expected_pages.add(response['pages'])
                for item in response['results']:
                    identifier = item['id']
                    ids.add(identifier)
                    try:
                        published = datetime.fromisoformat(item.get('webPublicationDate', '').replace('Z', '+00:00'))
                        if published.tzinfo is None:
                            raise ValueError('Publication timezone missing')
                        published = published.astimezone(timezone.utc)
                    except (ValueError, TypeError, AttributeError):
                        report['unknown_publication_date'] += 1
                        continue
                    if not start <= published.date().isoformat() <= end:
                        report['excluded_outside_range'] += 1
                        continue
                    rows[identifier] = {
                        'source': 'theguardian', 'source_id': identifier,
                        'url': item.get('webUrl', ''), 'title': item.get('webTitle', ''),
                        'published_at_utc': published.isoformat(),
                        'retrieved_at_utc': saved['retrieved_at_utc'],
                        'content_type': item.get('type', ''),
                        'tags': ','.join(tag['id'] for tag in item.get('tags', []) if 'id' in tag),
                        'body_text': item.get('fields', {}).get('bodyText', '') if include_body else ''}
                month['unique_ids'] = len(ids)
                if page_number >= max(1, response['pages']):
                    month['status'] = 'query_pages_fetched'
                    if len(totals) != 1 or len(expected_pages) != 1 or len(ids) != response['total']:
                        month['status'] = 'needs_review'
                        needs_review = True
                    break
                page_number += 1
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            month['status'] = 'failed'
            report['status'] = 'failed'
            report['errors'].append({'month': month_start, 'page': page_number, 'error': str(error)})
        if report['status'] in ('failed', 'request_budget_reached'):
            break
    report['months_not_started'] = len(windows) - len(report['months'])
    report['records'] = len(rows)
    report['records_with_body'] = sum(bool(row['body_text']) for row in rows.values())
    if include_body and report['records_with_body'] < len(rows):
        needs_review = True
    if (needs_review or report['unknown_publication_date'] or report['excluded_outside_range']) and report['status'] == 'query_pages_fetched':
        report['status'] = 'needs_review'
    ordered = sorted(rows.values(), key=lambda row: (row['published_at_utc'], row['source_id']))
    with (output / 'news.jsonl').open('w', encoding='utf-8') as stream:
        for row in ordered:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    with (output / 'news.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    write_json(output / 'coverage.json', report)
    return report


def make_fetcher(api_key):
    last_request = 0.0
    def fetch(params):
        nonlocal last_request
        time.sleep(max(0, 1.1 - (time.monotonic() - last_request)))
        url = ENDPOINT + '?' + urllib.parse.urlencode({**params, 'api-key': api_key})
        request = urllib.request.Request(url, headers={'User-Agent': 'NBA-course-research/1.0'})
        last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise RuntimeError('API response exceeds 20 MB; no page saved')
            return json.loads(data)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'API HTTP {error.code}; check access/quota before resuming') from None
        except (OSError, urllib.error.URLError):
            raise RuntimeError('API connection failed; check network access before resuming') from None
    return fetch


def news_params(start, end, page=1, page_size=10, query=None):
    params = query_params(start, end, page, include_body=True)
    params.update({'order-by': 'newest', 'page-size': page_size, 'show-fields': 'bodyText,byline'})
    if query:
        params['q'] = query
    return params


def parse_time(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('API timestamps must include a timezone')
    timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.replace(microsecond=(timestamp.microsecond // 1000) * 1000)


def prepare_news(payload, retrieved_at):
    """Keep one body copy per article; the full API response remains on disk."""
    received = parse_time(retrieved_at)
    documents = []
    seen = set()
    for article in payload['response']['results']:
        source_id = article['id']
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError('Missing or duplicate article ID')
        seen.add(source_id)
        fields = article.get('fields', {})
        body = fields.get('bodyText', '') or ''
        if not isinstance(body, str):
            raise ValueError('Article body must be text')
        documents.append({
            '_id': 'guardian:' + source_id,
            'source': 'theguardian',
            'source_id': source_id,
            'title': article.get('webTitle', ''),
            'url': article.get('webUrl', ''),
            'published_at_utc': parse_time(article['webPublicationDate']),
            'retrieved_at_utc': received,
            'content_type': article.get('type', ''),
            'byline': fields.get('byline', ''),
            'tags': article.get('tags', []),
            'body_text': body,
            'rag_ready': bool(body.strip()),
        })
    return documents


def store_news(collection, documents):
    """Repeated articles update in place; older saved batches cannot replace newer ones."""
    counts = {'inserted': 0, 'updated': 0, 'already_current': 0}
    for document in documents:
        query = {'_id': document['_id']}
        existing = collection.find_one(query, {'retrieved_at_utc': 1})
        if existing and isinstance(existing.get('retrieved_at_utc'), datetime):
            previous = existing['retrieved_at_utc']
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            if previous >= document['retrieved_at_utc']:
                counts['already_current'] += 1
                continue
        fields = {key: value for key, value in document.items() if key != '_id'}
        result = collection.update_one(query, {'$set': fields}, upsert=True)
        counts['inserted' if result.upserted_id is not None else 'updated'] += 1
    return counts


def check_connection(collection):
    collection.database.client.admin.command('ping')
    collection.create_index([('source', 1), ('published_at_utc', -1)])


def run_once(collection, output, params, fetch=None, resume=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / 'guardian_raw.json'
    if not resume and raw_path.exists():
        raise ValueError('Snapshot already exists. Use --resume or a new output folder')
    report = {'source': 'theguardian', 'status': 'pending', 'stage': 'mongodb_preflight',
              'mode': 'resume' if resume else 'fetch', 'request_attempts': 0,
              'automatic_retries': 0}
    write_json(output / 'collection_status.json', report)
    try:
        check_connection(collection)
        if resume:
            report['stage'] = 'read_local_backup'
            saved = json.loads(raw_path.read_text(encoding='utf-8'))
        else:
            report.update(stage='guardian_request', request_attempts=1, query=params)
            write_json(output / 'collection_status.json', report)
            payload = fetch(params)
            saved = {'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                     'query': params, 'payload': payload}
            report['stage'] = 'save_raw'
            write_json(raw_path, saved)
        report['stage'] = 'validate_response'
        response = validate_page(saved['payload'], saved['query']['page'])
        documents = prepare_news(saved['payload'], saved['retrieved_at_utc'])
        report.update(query=saved['query'], articles=len(documents),
                      articles_with_body=sum(doc['rag_ready'] for doc in documents),
                      source_total=response['total'], page=response['currentPage'],
                      source_pages=response['pages'], stage='mongodb_import')
        write_json(output / 'collection_status.json', report)
        report.update(store_news(collection, documents))
        ids = [document['_id'] for document in documents]
        verified = collection.count_documents({'_id': {'$in': ids}}) if ids else 0
        if verified != len(documents):
            raise RuntimeError('Stored article count does not match the input page')
        report.update(status='completed', stage='done', verified_documents=verified)
    except Exception as error:
        # Error messages can expose credentials. Keep only safe diagnostic identifiers.
        report.update(status='failed', error_type=type(error).__name__)
        code = getattr(error, 'code', None)
        if isinstance(code, int):
            report['error_code'] = code
    finally:
        write_json(output / 'collection_status.json', report)
    return report


def run_backfill(args):
    """Backfill to local JSON/CSV only; no MongoDB connection in this mode."""
    windows = month_windows(args.start, args.end)
    if args.max_requests is None:
        args.max_requests = 100
    mode = 'body' if args.include_body else 'metadata'
    output = ROOT / 'data/collected' / f'guardian_{args.start}_{args.end}_{mode}'
    if args.plan:
        print(json.dumps({'start': args.start, 'end': args.end, 'month_windows': len(windows),
                          'max_requests_this_run': args.max_requests, 'output': str(output),
                          'query_example': query_params(*windows[0], 1, args.include_body)}, indent=2))
        return 0
    key = os.environ.get('GUARDIAN_API_KEY', '').strip()
    if not key or key == 'test':
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / 'preflight.json', {'status': 'requires_api_key', 'checked_at_utc': utc_now(),
                   'requests_made': 0, 'reason': 'Set your own GUARDIAN_API_KEY environment variable'})
        print('Set your own GUARDIAN_API_KEY. No API requests made.', file=sys.stderr)
        return 2
    report = collect(args.start, args.end, output, make_fetcher(key), args.max_requests, args.include_body)
    print(json.dumps({field: report[field] for field in ('status', 'records', 'requests_this_run')}, indent=2))
    print(output)
    return 0 if report['status'] == 'query_pages_fetched' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='nba_project')
    parser.add_argument('--collection', default='news_articles')
    parser.add_argument('--start', default='2023-11-17')
    parser.add_argument('--end', default='2026-11-17')
    parser.add_argument('--page', type=int, help='MongoDB single-page mode: default 1')
    parser.add_argument('--page-size', type=int, help='MongoDB single-page mode: default 10')
    parser.add_argument('--query', help='Optional additional search, e.g. injury OR injured')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--resume', type=Path, help='Import a saved MongoDB batch without a Guardian call')
    modes.add_argument('--check-connection', action='store_true')
    modes.add_argument('--backfill', action='store_true', help='Monthly local JSON/CSV backfill; does not write MongoDB')
    parser.add_argument('--max-requests', type=int, help='Backfill request budget; default 100')
    parser.add_argument('--include-body', action='store_true', help='Include article bodies in local backfill')
    parser.add_argument('--plan', action='store_true', help='Preview --backfill scope without requests or writes')
    args = parser.parse_args()
    try:
        if date.fromisoformat(args.start) > date.fromisoformat(args.end):
            raise ValueError('--start must not be after --end')
    except ValueError as error:
        parser.error(str(error))
    if not args.backfill and (args.plan or args.include_body or args.max_requests is not None):
        parser.error('--plan, --include-body and --max-requests require --backfill')
    if args.max_requests is not None and args.max_requests < 1:
        parser.error('--max-requests must be positive')
    if args.backfill:
        if args.page is not None or args.page_size is not None or args.query is not None:
            parser.error('--page, --page-size and --query belong to the single-page MongoDB mode')
        return run_backfill(args)
    args.page = 1 if args.page is None else args.page
    args.page_size = 10 if args.page_size is None else args.page_size
    if args.page < 1 or not 1 <= args.page_size <= 50:
        parser.error('--page must be positive and --page-size must be 1 to 50')
    if args.resume and not (args.resume / 'guardian_raw.json').is_file():
        parser.error('--resume must point to a batch containing guardian_raw.json')
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
        with MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=10000,
                         connectTimeoutMS=10000, socketTimeoutMS=30000) as client:
            collection = client[args.database][args.collection]
            if args.check_connection:
                check_connection(collection)
                print(f'Connected: {args.database}.{args.collection}. No Guardian request made.')
                return 0
            fetch = None
            if not args.resume:
                key = os.environ.get('GUARDIAN_API_KEY', '').strip() or getpass.getpass('Guardian API key (hidden): ')
                if not key or key == 'test':
                    print('Your own Guardian API key is required.', file=sys.stderr)
                    return 1
                fetch = make_fetcher(key)
            batch = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
            output = args.resume or ROOT / 'data/collected' / ('guardian_mongodb_' + batch)
            params = news_params(args.start, args.end, args.page, args.page_size, args.query)
            report = run_once(collection, output, params, fetch, resume=bool(args.resume))
            print(json.dumps(report, indent=2))
            print('Local backup: ' + str(output.resolve()))
            if report['status'] != 'completed':
                if report['stage'] == 'mongodb_preflight':
                    print('Check Atlas database user permissions, URI and IP access list. No API request made.')
                elif (output / 'guardian_raw.json').is_file():
                    print('The API response is saved. After fixing the issue, use --resume with this folder.')
                else:
                    print('Check Guardian key, API access and network. No automatic retry was made.')
                return 1
    except Exception as error:
        print(f'Operation failed ({type(error).__name__}). Check MongoDB configuration and network.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
