# Data catalog and interpretation guide

Metadata was inspected locally on 2026-11-19. No cloud database or API was queried. Counts describe saved files, not current provider coverage or live database contents.

| File | How to use it |
| --- | --- |
| `dataset_catalog.csv` | Find every data file by category, path, source, grain, observed dates, count and limitations. Open as UTF-8 in Excel. |
| `field_dictionary.csv` | Definitions of CSV fields and important nested JSON paths, including timestamp and join semantics. |
| `sqlite_tables.csv` | All 16 historical tables with measured row counts and intended row meaning. |
| `sqlite_columns.csv` | Every SQLite column, declared type, nullability/PK flags and a description or explicit interpretation limit. |
| `sqlite_schema.json` | Exact local SQLite table/column/index/foreign-key declarations. Does not claim RDS has the same constraints. |
| `file_manifest.csv` | Size and SHA-256 for original data files; excludes metadata, Python scripts, caches and editor files. |

All paths are relative to the project root, not this metadata folder. Blank metadata means unavailable or not applicable. Row counts for JSON identify the counted array; dictionaries such as status files are single metadata objects, not one article or one game. SQLite row counts are in `sqlite_tables.csv` rather than a misleading combined count.

## Historical NBA

`data/raw/nba.sqlite` is the preserved source database. Local download markers identify the Kaggle dataset `wyattowalsh/basketball`, version 238; the original source/licensing terms were not revalidated during this handoff. Do not treat the proposal as a data dictionary. Schema declarations are inspected directly; explanatory descriptions are project interpretations, not an official upstream codebook.

The measured `game.game_date` range is 1946-11-01 through 2023-06-12. This range is for `game`, not a claim that every table covers every season. Use `game_id` for historical game joins, `team.id` for team references, and `player.id` for historical player references. Candidate relationships have not all been checked for uniqueness, missing keys or referential integrity. Source IDs can contain leading zeros.

`game` stores paired home/away results; `play_by_play` stores game events. Final points, win/loss flags and the same game's events are postgame information. Build pregame features using earlier games only. Player activity, roster and team staff fields reflect the historical source snapshot, not current 2026 status. Source event-type codes remain uninterpreted unless an upstream codebook is obtained.

## Odds

Use `odds_mongodb_20261118T021208Z_ccbe3ddf/odds_raw.json` for the 14-game successful Atlas sample, and the earlier `odds_sample_20261118T0022108258385Z/odds_sample.csv` for the flattened 9-game / 118-quote sample. They are distinct snapshots, not two representations of the same capture.

JSON array element = game snapshot; CSV row = event × bookmaker × market × outcome at capture time. Only `h2h` / moneyline was collected. Odds are decimal. Keep both collection time and bookmaker/market update time. Compare the same event, market and outcome; differing collection times are not simultaneous quotes. Provider event IDs are not NBA historical `game_id` values.

The `before_export_fix` CSV contains the known `System.Object[]` export defect. It is retained for audit and must not be used for analysis. Its companion pre-fix status file is also historical. Failed batch status files are evidence of failed attempts, not datasets with successful observations.

## Guardian news

`guardian_raw.json` contains `{retrieved_at_utc, query, payload}`. Articles are at `payload.response.results[]`, not at the wrapper root. The local sample contains 10 articles with bodies, published 2026-10-28 through 2026-11-15. The requested search window was 2023-11-17 through 2026-11-17. These are different concepts: three-year backfill is not complete.

`id` is the source article ID, `webUrl` is the citation URL, `webPublicationDate` is publication time and `fields.bodyText` is the body. The response's `total=389` was the matching count at that request, not the number downloaded. Keyword tags are source metadata, not guaranteed resolved player/team IDs. No chunks, embeddings or vector index are included.

## Injuries, summaries and mappings

`staging/injury_reports/*.web-extract.txt` are captured text extracts of three official NBA PDFs. Original PDF download count is zero. In these extracts `P0` is a zero-based page marker; CSV `source_page` is one-based. Retain source URL, report time, retrieval time and evidence location together.

`injury_records.csv`: one player status in one report for one game. `team_submissions.csv`: one team/game/report marked not yet submitted. Neither an absent player nor a not-submitted team means available/healthy. The 124 injury rows are report snapshots, not 124 unique players.

`news_seed.json` and `news_index.csv` contain 8 early summaries/index entries, not Guardian's 10 full article bodies. Some source publication timezones remain unverified. `source_catalog.csv` tracks both reports and summaries and states which originals exist. The 50 unmatched player names are retained rather than assigned invented IDs.

Join `document_links.document_id` to `source_catalog.document_id`, `document_links.project_game_id` to `game_map.project_game_id`, and injury `nba_team_id` to historical `team.id` when populated. `project_game_id` is a locally constructed key, not an NBA/Odds provider ID. `nba_game_id` and `odds_api_event_id` are unresolved in the current game map. `entity_map` records the method used for each name match. `status_changes.csv` compares observed report snapshots; it does not prove that a report caused an odds movement.

## Audit and provenance

`collection_status.json` records the outcome of each collection/import attempt. `download_attempts.json` records PDF download attempts; `pdf_download_queue.json` lists discovered URLs and intended local paths, not proof of downloads. `preflight.json` records an earlier collection preflight. Quota values are historical response values, not current balances.

Raw files and source timestamps were preserved during organization. CSV metadata is UTF-8 with a BOM for Excel. Metadata is a handoff snapshot and is not automatically refreshed by the collection scripts.
