"""Build auditable CSVs from captured NBA report text and reviewed news summaries.

Run from any directory: python scripts/build_injury_news_sample.py
This is an offline sample builder. It does not download files or write to RDS.
"""

import csv
import hashlib
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data/collected/injury_news_2026-11-17'
CAPTURED_AT = '2026-11-17T22:46:21Z'


def identifier(prefix, value):
    return prefix + '_' + hashlib.sha256(value.encode()).hexdigest()[:16]


def normalize_name(name):
    if ', ' in name:
        last, first = name.split(', ', 1)
        name = first + ' ' + last
    plain = unicodedata.normalize('NFKD', name)
    return re.sub(r'[^a-z0-9]', '', plain.encode('ascii', 'ignore').decode().lower())


def write_csv(name, rows):
    if not rows:
        raise ValueError('Unexpected empty output: ' + name)
    with (OUTPUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_report(path, team_aliases):
    """Carry table context across wrapped lines; preserve unsubmitted teams."""
    content = path.read_text(encoding='utf-8')
    url = content.splitlines()[0].removeprefix('Source: ')
    stamp = re.search(r'Injury-Report_(\d{4}-\d{2}-\d{2}_\d{2}_\d{2}[AP]M)', url)[1]
    # This captured batch is in November 2026, after US daylight saving ends.
    local_time = datetime.strptime(stamp, '%Y-%m-%d_%I_%M%p')
    report_time = local_time.replace(tzinfo=timezone(timedelta(hours=-5)))
    report_utc = report_time.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    doc_id = identifier('doc', url)
    rows, pending = [], None
    game_date = game_time = matchup = team = ''

    for line in content.splitlines():
        source = re.match(r'L(\d+)@P(\d+)(?:-\d+)?: (.*)', line)
        if not source:
            continue
        line_number, page, text = source.groups()
        text = text.split('Injury Report:')[0].strip()
        if not text or text.startswith(('Page ', 'Game Date ')):
            continue
        date_match = re.match(r'(\d{2}/\d{2}/\d{4})\s+', text)
        if date_match:
            game_date = datetime.strptime(date_match[1], '%m/%d/%Y').date().isoformat()
            text = text[date_match.end():]
        time_match = re.match(r'(\d{2}:\d{2} \(ET\))\s+', text)
        if time_match:
            game_time = time_match[1]
            text = text[time_match.end():]
        matchup_match = re.match(r'([A-Z]{3}@[A-Z]{3})\s+', text)
        if matchup_match:
            matchup, team = matchup_match[1], ''
            text = text[matchup_match.end():]
        for alias in sorted(team_aliases, key=len, reverse=True):
            if text.startswith(alias + ' '):
                team = alias
                text = text[len(alias):].strip()
                break

        status_match = re.match(r'(.+?) (Out|Questionable|Doubtful|Probable|Available)(?:\s+(.*))?$', text)
        unsubmitted = text == 'NOT YET SUBMITTED'
        if status_match or unsubmitted:
            if pending:
                rows.append(pending)
            if not all((game_date, matchup, team)):
                raise ValueError(f'Missing table context: {path.name}:{line_number}: {text}')
            if status_match:
                player, status, reason = status_match.groups()
            else:
                player, status, reason = '', 'NOT_YET_SUBMITTED', ''
            pending = {
                'document_id': doc_id, 'source_url': url,
                'report_at_utc': report_utc, 'report_timezone': 'America/New_York',
                'retrieved_at_utc': CAPTURED_AT, 'game_date': game_date,
                'game_time_report': game_time, 'matchup': matchup,
                'project_game_id': 'nba-' + game_date + '-' + matchup.replace('@', '-'),
                'team_name_source': team, 'team_abbreviation': team_aliases[team]['abbreviation'],
                'nba_team_id': team_aliases[team]['id'], 'player_name_source': player,
                'status': status, 'reason': reason or '', 'source_page': int(page) + 1,
                'source_line': int(line_number), 'capture_method': 'web_pdf_text_extraction',
            }
        elif pending:
            pending['reason'] = (pending['reason'] + ' ' + text).strip()
        else:
            raise ValueError('Unparsed content: ' + text)
    if pending:
        rows.append(pending)
    original_path = ROOT / 'data/raw/injury_reports' / Path(url).name
    original_ok = original_path.is_file() and original_path.read_bytes().startswith(b'%PDF-')
    document = {
        'document_id': doc_id, 'source_type': 'official_injury_report', 'publisher': 'NBA',
        'source_url': url, 'label': Path(url).name,
        'source_time_display': local_time.isoformat() + ' America/New_York',
        'timestamp_kind': 'report_snapshot', 'source_time_utc': report_utc,
        'retrieved_at_utc': CAPTURED_AT, 'content_kind': 'web_pdf_text_extract',
        'local_path': path.relative_to(ROOT).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'original_downloaded': original_ok,
        'original_file_path': original_path.relative_to(ROOT).as_posix() if original_ok else '',
        'original_sha256': hashlib.sha256(original_path.read_bytes()).hexdigest() if original_ok else '',
        'download_status': 'downloaded_pdf' if original_ok else 'pending_network_access',
    }
    return rows, document


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    uri = (ROOT / 'data/raw/nba.sqlite').as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        teams = [dict(row) for row in conn.execute('SELECT id, abbreviation, full_name FROM team')]
        players = [dict(row) for row in conn.execute('SELECT id, full_name FROM player')]
    aliases = {row['full_name']: row for row in teams}
    aliases['LA Clippers'] = aliases['Los Angeles Clippers']
    by_abbreviation = {row['abbreviation']: row for row in teams}
    players_by_name = {}
    for player in players:
        players_by_name.setdefault(normalize_name(player['full_name']), []).append(player)

    all_rows, documents = [], []
    for path in sorted((ROOT / 'data/staging/injury_reports').glob('*.web-extract.txt')):
        rows, document = parse_report(path, aliases)
        all_rows.extend(rows)
        documents.append(document)

    injuries, submissions, entity_map = [], [], {}
    for row in all_rows:
        if not row['player_name_source']:
            submissions.append(row)
            continue
        matches = players_by_name.get(normalize_name(row['player_name_source']), [])
        nba_id = matches[0]['id'] if len(matches) == 1 else ''
        row['nba_player_id'] = nba_id
        row['player_match_status'] = 'normalized_name_match' if nba_id else 'unmatched_in_historical_database'
        row['record_id'] = identifier('injury', '|'.join(str(row[k]) for k in ('document_id', 'project_game_id', 'nba_team_id', 'player_name_source')))
        injuries.append(row)
        entity_map[('player', row['player_name_source'])] = {
            'entity_type': 'player', 'source_name': row['player_name_source'], 'nba_id': nba_id,
            'match_status': row['player_match_status'], 'reference': 'data/raw/nba.sqlite:player',
        }
    for name, row in aliases.items():
        entity_map[('team', name)] = {'entity_type': 'team', 'source_name': name, 'nba_id': row['id'],
                                    'match_status': 'explicit_team_alias', 'reference': 'data/raw/nba.sqlite:team'}
    for row in teams:
        entity_map[('team', row['abbreviation'])] = {
            'entity_type': 'team', 'source_name': row['abbreviation'], 'nba_id': row['id'],
            'match_status': 'explicit_team_abbreviation', 'reference': 'data/raw/nba.sqlite:team',
        }

    games, links = {}, {}
    for row in all_rows:
        game_id = row['project_game_id']
        away, home = row['matchup'].split('@')
        games[game_id] = {
            'project_game_id': game_id, 'game_date': row['game_date'], 'matchup': row['matchup'],
            'away_nba_team_id': by_abbreviation[away]['id'], 'home_nba_team_id': by_abbreviation[home]['id'],
            'nba_game_id': '', 'odds_api_event_id': '',
            'match_status': 'pending_external_ids_current_game_not_in_historical_database',
        }
        key = (row['document_id'], game_id)
        links[key] = {'document_id': key[0], 'project_game_id': key[1], 'relation': 'explicit_matchup',
                      'temporal_status': 'report_timestamp_available'}

    seed_path = ROOT / 'data/staging/news/news_seed.json'
    seed = json.loads(seed_path.read_text(encoding='utf-8'))
    news = []
    for article in seed['articles']:
        doc_id = identifier('doc', article['url'])
        for player in article['players']:
            matches = players_by_name.get(normalize_name(player), [])
            nba_id = matches[0]['id'] if len(matches) == 1 else ''
            entity_map[('player', player)] = {
                'entity_type': 'player', 'source_name': player, 'nba_id': nba_id,
                'match_status': 'normalized_name_match' if nba_id else 'unmatched_in_historical_database',
                'reference': 'data/raw/nba.sqlite:player',
            }
        news.append({
            'document_id': doc_id, 'label': article['label'], 'publisher': article['publisher'],
            'source_type': article['source_type'], 'source_url': article['url'],
            'source_time_display': article['published_at_source'], 'timestamp_kind': article['timestamp_kind'],
            'source_time_utc': article['published_at_utc'], 'timezone_status': article['timezone_status'],
            'summary_file': seed_path.relative_to(ROOT).as_posix(),
            'summary_lookup_key': article['url'], 'content_kind': 'assistant_summary',
            'teams': '|'.join(article['teams']), 'players': '|'.join(article['players']),
            'topic_group': article['topic_group'], 'retrieved_at_utc': seed['retrieved_at_utc'],
        })
        documents.append({
            'document_id': doc_id, 'source_type': article['source_type'], 'publisher': article['publisher'],
            'source_url': article['url'], 'label': article['label'],
            'source_time_display': article['published_at_source'], 'timestamp_kind': article['timestamp_kind'],
            'source_time_utc': article['published_at_utc'], 'retrieved_at_utc': seed['retrieved_at_utc'],
            'content_kind': 'assistant_summary', 'local_path': seed_path.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(seed_path.read_bytes()).hexdigest(),
            'original_downloaded': False, 'original_file_path': '', 'original_sha256': '',
            'download_status': 'summary_only_no_full_article_copy',
        })
        for relation in article['game_links']:
            game_id = 'nba-' + relation['game_date'] + '-' + relation['matchup'].replace('@', '-')
            if game_id not in games:
                raise ValueError('News game has no report reference: ' + game_id)
            links[(doc_id, game_id)] = {
                'document_id': doc_id, 'project_game_id': game_id, 'relation': relation['relation'],
                'temporal_status': 'needs_tipoff_check' if article['published_at_utc'] else 'timezone_unverified',
            }

    changes, previous = [], {}
    for row in sorted(injuries, key=lambda r: r['report_at_utc']):
        key = (row['project_game_id'], row['nba_team_id'], row['player_name_source'])
        old = previous.get(key)
        if old and (old['status'], old['reason']) != (row['status'], row['reason']):
            changes.append({
                'project_game_id': key[0], 'player_name_source': key[2],
                'previous_document_id': old['document_id'], 'current_document_id': row['document_id'],
                'previous_report_at_utc': old['report_at_utc'], 'current_report_at_utc': row['report_at_utc'],
                'previous_status': old['status'], 'current_status': row['status'],
                'previous_reason': old['reason'], 'current_reason': row['reason'],
            })
        previous[key] = row

    write_csv('injury_records.csv', injuries)
    write_csv('team_submissions.csv', submissions)
    write_csv('news_index.csv', news)
    write_csv('source_catalog.csv', documents)
    write_csv('entity_map.csv', list(entity_map.values()))
    write_csv('game_map.csv', list(games.values()))
    write_csv('document_links.csv', list(links.values()))
    write_csv('status_changes.csv', changes)
    pending = [{'document_id': d['document_id'], 'url': d['source_url'],
                'target_path': 'data/raw/injury_reports/' + Path(d['source_url']).name}
               for d in documents if d['source_type'] == 'official_injury_report']
    (OUTPUT / 'pdf_download_queue.json').write_text(json.dumps(pending, indent=2) + '\n', encoding='utf-8')
    checks = {
        'report_count': len(pending), 'injury_record_count': len(injuries),
        'unsubmitted_team_snapshot_count': len(submissions), 'news_count': len(news),
        'referenced_game_count': len(games), 'document_link_count': len(links),
        'status_change_count': len(changes),
        'original_pdf_download_count': sum(d['original_downloaded'] for d in documents),
        'full_news_article_count': 0,
        'unmatched_unique_player_count': len({normalize_name(r['source_name']) for r in entity_map.values()
                                            if r['entity_type'] == 'player' and not r['nba_id']}),
        'news_timezone_unverified_count': sum(not n['source_time_utc'] for n in news),
        'limitations': ['PDF text captured through web tool; original files pending download.',
                       'News contains short assistant summaries, not original article bodies.',
                       'Newer players may be absent from the historical player table.',
                       'No external game IDs or pregame eligibility have been asserted.',
                       'Not submitted or absent from the report does not mean healthy.'],
    }
    (OUTPUT / 'collection_status.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    build_overview(checks, news, documents)
    print(json.dumps(checks, indent=2))


def build_overview(checks, news, documents):
    esc = html.escape
    news_rows = ''.join('<tr><td>' + esc(n['label']) + '</td><td>' + esc(n['publisher']) + '</td><td>'
                        + esc(n['source_time_display']) + '</td><td><a href="'
                        + esc(n['source_url'], quote=True) + '">来源</a></td></tr>' for n in news)
    reports = ''.join('<li><a href="' + esc(d['source_url'], quote=True) + '">' + esc(d['label'])
                      + '</a>：网页提取文本已保存；原文件状态：' + ('已下载' if d['original_downloaded'] else '待下载') + '。</li>'
                      for d in documents if d['source_type'] == 'official_injury_report')
    files = ['injury_records.csv','news_index.csv','source_catalog.csv','entity_map.csv','game_map.csv',
             'document_links.csv','status_changes.csv','team_submissions.csv','collection_status.json']
    file_links = ' · '.join('<a href="'+f+'">'+f+'</a>' for f in files)
    output = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NBA 数据采集：首批结果与 Odds API 入门</title><style>
body{{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:1080px;margin:35px auto;padding:0 24px;color:#233344}}
h1,h2{{line-height:1.3;color:#183d55}}h1{{font-size:27px}}h2{{font-size:21px;margin-top:30px}}
a{{color:#176b94}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;text-align:left;border:1px solid #dce4e8;vertical-align:top}}
th{{background:#edf4f7}}.notice{{background:#fff7e8;padding:16px;border-left:4px solid #d39c39}}code,pre{{background:#f1f5f8;padding:3px 6px}}pre{{overflow:auto;padding:15px}}.scroll{{overflow:auto}}
</style><h1>NBA 数据采集：首批结果与 Odds API 入门</h1><p>采集日期：2026-11-17。已有 RDS 不受影响；本批产物保存于本地。</p>
<h2>已经保存什么</h2><p><strong>{checks['report_count']} 个官方报告版本的文本、{checks['injury_record_count']} 条球员状态记录、{checks['news_count']} 条新闻摘要。</strong>
官方报告覆盖 {checks['referenced_game_count']} 场比赛；新闻仅覆盖其中部分比赛，不能把这个数字理解为完整的比赛数据包。</p>
<p class="notice">本次采集时命令行联网下载受限：当前原始 PDF 数为 {checks['original_pdf_download_count']}，新闻全文数为 0。新闻文件是明确标注的短摘要。
这些材料可用于核对 metadata 和原型检索；完整原文采集仍待补齐。没有自动采集任务在后台运行。</p>
<p>{file_links}</p><h2>伤病报告</h2><ul>{reports}</ul>
<p>每行表示“一个报告时点、一场比赛、一名球员”的状态；不是伤病事件总数。
另存 {checks['unsubmitted_team_snapshot_count']} 条“尚未提交”记录；不能解释成没有伤病。
检测到 {checks['status_change_count']} 条跨报告状态／原因变化，见 status_changes.csv。</p>
<h2>相关新闻</h2><p>同一公告的不同报道用 topic_group 归组。部分页面不标时区，UTC 时间留空；旧新闻只作背景，不自动认定赛前可用。</p>
<p><a href="../../staging/news/news_seed.json">查看 8 条新闻摘要（JSON）</a>；使用 source_url 查找相应摘要，非文章全文。</p>
<div class="scroll"><table><thead><tr><th>摘要标签（自拟）</th><th>发布方</th><th>页面时间</th><th>原文</th></tr></thead><tbody>{news_rows}</tbody></table></div>
<h2>你怎样研究 The Odds API：按这个顺序</h2><ol>
<li>打开 <a href="https://the-odds-api.com/">官网</a>，看 Starter 免费套餐：目前 500 credits/月，不含历史赔率。注册后把 key 保存在本机环境变量，勿放进共享文件。</li>
<li>打开 <a href="https://the-odds-api.com/liveapi/guides/v4/">V4 文档</a>，先读 GET sports、GET odds、Usage Quota Costs、Response Headers。</li>
<li>第一次只选 basketball_nba、regions=us、markets=h2h、oddsFormat=decimal。返回中检查 id、commence_time、主客队、bookmakers、last_update 和 outcomes。</li>
<li>看 x-requests-last 与 x-requests-remaining；上述单市场单地区赔率请求通常用 1 credit，可包含多场比赛。</li>
<li>把一次真实 JSON 存下来，再整理字段。Dashboard 读取保存的数据。建议起步每天 6 次，30 天约 180 credits，另留调试额度。</li></ol>
<pre>GET https://api.the-odds-api.com/v4/sports/basketball_nba/odds
regions=us &amp; markets=h2h &amp; oddsFormat=decimal
Authentication: x-api-key header</pre>
<p>第一轮研究目标：看懂一场比赛的两家公司报价，以及一次请求花了多少额度。免费套餐采当前报价，不能免费补回旧赔率。
若当前已无本批比赛赔率，就在获得 key 后选下一批比赛，沿用这里的 metadata 结构。</p>
<h2>如何补齐原始 PDF</h2><p>在能联网的本机终端、项目根目录运行：</p>
<pre>python scripts/download_injury_pdfs.py</pre><p>脚本按清单下载到 data/raw/injury_reports/，验证 PDF 文件头、记录 SHA-256 和结果。
下载后重新生成整理表：<code>python scripts/build_injury_news_sample.py</code>。
伤病原文可用于后续解析；新闻全文需另行取得可使用的文本，不能把摘要标为原文。</p>
<h2>metadata 如何接入后续工作</h2><p>球队 ID 来自本地 NBA 数据库。球员仅做唯一名称匹配，{checks['unmatched_unique_player_count']} 个未匹配名称保留待核对。
game_map.csv 的项目比赛 ID 是本地标识，NBA game_id 和 Odds API event id 尚为空，待拿到真实 API 返回后补充。</p>
<p>source_catalog.csv 记录来源、时间、内容类型和文件位置；document_links.csv 记录文档关联的比赛及关联依据。
先核对本批数据，再写入 MongoDB／RDS、上传 S3。当前没有执行云端写入。</p></html>'''
    (OUTPUT / 'START_HERE.html').write_text(output, encoding='utf-8')


if __name__ == '__main__':
    main()
