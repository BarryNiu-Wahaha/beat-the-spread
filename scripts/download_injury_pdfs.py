"""Download the three discovered NBA PDFs; no credentials or cloud writes.

Run: python scripts/download_injury_pdfs.py
Re-run build_injury_news_sample.py afterward to refresh the metadata status.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/collected/injury_news_2026-11-17'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    queue = json.loads((BATCH / 'pdf_download_queue.json').read_text(encoding='utf-8'))
    results = []
    for item in queue[:args.limit]:
        target = (ROOT / item['target_path']).resolve()
        if not target.is_relative_to(ROOT / 'data/raw/injury_reports'):
            raise ValueError('Unexpected output path')
        if not item['url'].startswith('https://ak-static.cms.nba.com/referee/injury/'):
            raise ValueError('Unexpected download host')
        result = {**item, 'attempted_at_utc': datetime.now(timezone.utc).isoformat(),
                  'status': '', 'sha256': '', 'bytes': 0, 'error': ''}
        try:
            if target.is_file():
                data = target.read_bytes()
                if not data.startswith(b'%PDF-'):
                    raise ValueError('Existing file is not a PDF; left unchanged')
                result['status'] = 'already_present'
            else:
                request = urllib.request.Request(item['url'], headers={'User-Agent': 'NBA-course-research/1.0'})
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = response.read(20_000_001)
                if len(data) > 20_000_000 or not data.startswith(b'%PDF-'):
                    raise ValueError('Response is too large or not a PDF')
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as f:
                    f.write(data)
                result['status'] = 'downloaded'
            result.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        except (OSError, urllib.error.URLError, ValueError) as error:
            result.update(status='failed', error=str(error))
        results.append(result)
        print(result['status'], Path(item['target_path']).name)
    (BATCH / 'download_attempts.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    if any(r['status'] == 'failed' for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
