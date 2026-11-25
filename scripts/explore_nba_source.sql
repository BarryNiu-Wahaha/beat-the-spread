-- NBA source exploration: RDS MySQL (not SQLite).
-- Open in MySQL Workbench / DBeaver and run selected sections individually.
-- Select your existing NBA database first; nba_source was the migration default.
-- Uncomment and edit only if needed:
-- USE nba_source;
-- All queries below are read-only. No tables, indexes or data are changed.
-- The migration copied columns/data, NOT indexes. Even one-game filters can
-- scan all 13.6 million events. LIMIT caps output, not necessarily work.
-- Start with sections 1-5; run event sections only when needed.

SELECT table_name, table_rows AS estimated_rows,
       ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
ORDER BY data_length + index_length DESC;

-- Teams and players: historical source snapshot, not current rosters.
SELECT id, full_name, abbreviation, city, year_founded
FROM team
ORDER BY full_name;

SELECT id, full_name, is_active
FROM player
WHERE full_name LIKE '%James%'
ORDER BY full_name
LIMIT 30;

-- Game coverage and categories. Rows are not necessarily unique games.
-- Date strings use ISO ordering in the source; coverage is for game only.
SELECT COUNT(*) AS game_rows, COUNT(DISTINCT game_id) AS distinct_game_ids,
       MIN(game_date) AS first_game_date, MAX(game_date) AS last_game_date,
       SUM(CASE WHEN game_id IS NULL OR TRIM(game_id) = '' THEN 1 ELSE 0 END)
           AS missing_game_ids
FROM game;

SELECT season_type, COUNT(*) AS game_rows,
       COUNT(DISTINCT game_id) AS distinct_game_ids
FROM game
GROUP BY season_type
ORDER BY game_rows DESC;

-- Resolve duplicate IDs before joining events to game, to avoid multiplying rows.
SELECT game_id, COUNT(*) AS rows_per_id
FROM game
GROUP BY game_id
HAVING COUNT(*) > 1
ORDER BY rows_per_id DESC, game_id
LIMIT 30;

-- Take a look at how many duplicate games have the same game ID.
SELECT
    COUNT(*) AS total_rows,
    COUNT(DISTINCT game_id) AS unique_games,
    COUNT(*) - COUNT(DISTINCT game_id) AS duplicate_rows
FROM game;

-- Find out that it is because there's two different name about All Star Data.
SELECT COUNT(*) FROM
(SELECT
    game_id,
    COUNT(*) AS row_count,
    COUNT(DISTINCT season_type) AS season_type_count,
    GROUP_CONCAT(
        DISTINCT season_type
        ORDER BY season_type
        SEPARATOR ' | '
    ) AS season_types
FROM game
GROUP BY game_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, game_id) a;

-- Browse recent regular-season results. Change dates/team abbreviation to see different games.
-- End date is exclusive.
SELECT game_id, game_date, season_id, season_type,
       team_abbreviation_home, team_abbreviation_away,
       pts_home, pts_away,
       pts_home - pts_away AS home_final_margin,
       pts_home + pts_away AS final_total
FROM game
WHERE season_type = 'Regular Season'
  AND game_date >= '2022-10-01' AND game_date < '2023-07-01'
  AND (team_abbreviation_home = 'LAL' OR team_abbreviation_away = 'LAL')
ORDER BY game_date DESC, game_id
LIMIT 30;

-- One known game: 1996-11-01 Lakers vs Suns. Keep leading zeros in IDs.
-- Replace '0029600012' consistently below to explore another game.
SELECT game_id, game_date, team_name_home, team_name_away, pts_home, pts_away
FROM game
WHERE game_id = '0029600012';

-- EXPLAIN shows the plan without executing the event query.
-- asking MySQL: How are you going to execute this query?
EXPLAIN SELECT eventnum, period, pctimestring
FROM play_by_play WHERE game_id = '0029600012'
ORDER BY period, eventnum LIMIT 100;

-- Read events in source sequence, not by clock alone (clocks can tie).
-- score is often NULL on non-scoring events; NULL does NOT mean 0-0.
-- wctimestring and pctimestring are different clocks.
-- SELECT game_id, period, eventnum, pctimestring, wctimestring,
--        eventmsgtype, eventmsgactiontype,
--        homedescription, visitordescription, neutraldescription,
--        score, scoremargin, player1_name, player1_team_id
-- FROM play_by_play
-- WHERE game_id = '0029600012'
-- ORDER BY period, eventnum
-- LIMIT 100;
-- This query took too long. We may need HDFS to query it faster.

SELECT * FROM play_by_play LIMIT 10;

-- Inspect event codes and descriptions before assigning basketball labels.
-- Events are NOT possessions. These counts are not turnover/shot frequencies
-- per possession, and participant names do not establish a full lineup.
SELECT eventmsgtype, eventmsgactiontype, COUNT(*) AS event_rows,
       MIN(COALESCE(homedescription, visitordescription, neutraldescription))
           AS example_description
FROM play_by_play
WHERE game_id = '0029600012'
GROUP BY eventmsgtype, eventmsgactiontype
ORDER BY eventmsgtype, eventmsgactiontype;
-- This query took too long. We may need HDFS to query it faster.

-- One-game quality checks. Missing scores on non-scoring events are expected.
SELECT period, COUNT(*) AS event_rows,
       MIN(eventnum) AS first_eventnum, MAX(eventnum) AS last_eventnum,
       SUM(CASE WHEN pctimestring IS NULL OR TRIM(pctimestring) = ''
                THEN 1 ELSE 0 END) AS missing_game_clocks,
       SUM(CASE WHEN score IS NULL OR TRIM(score) = ''
                THEN 1 ELSE 0 END) AS missing_score_strings
FROM play_by_play
WHERE game_id = '0029600012'
GROUP BY period
ORDER BY period;
-- This query took too long. We may need HDFS to query it faster.

SELECT game_id, eventnum, COUNT(*) AS rows_per_event_number
FROM play_by_play
WHERE game_id = '0029600012'
GROUP BY game_id, eventnum
HAVING COUNT(*) > 1
ORDER BY eventnum;
-- This query took too long. We may need HDFS to query it faster.

-- Independently inspect period scores; no unchecked multi-table join.
SELECT game_id, team_abbreviation_home, team_abbreviation_away,
       pts_qtr1_home, pts_qtr1_away, pts_qtr2_home, pts_qtr2_away,
       pts_qtr3_home, pts_qtr3_away, pts_qtr4_home, pts_qtr4_away,
       pts_ot1_home, pts_ot1_away, pts_home, pts_away
FROM line_score
WHERE game_id = '0029600012';

