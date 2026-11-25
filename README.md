# DraftKings NBA Game Monitoring & What-if Simulation Platform

[Current proposal — Word, revised 21 November 2026](docs/proposal/DraftKings%20Project%20Proposal.docx): the two-page course proposal. [AGENTS.md](AGENTS.md) records current decisions, evidence and implementation steps. The simulator, warehouse, RAG and application remain to be implemented.

The platform will let sportsbook traders compare a baseline with scenario assumptions during historical NBA replay. One engine will use conditional empirical sampling and Monte Carlo simulation, preserving historical points-duration combinations. Traders can adjust **3PT Frequency, 2PT Frequency, Turnover Rate, Pace and FT Frequency** through sampling weights at key moments. Overrides apply to the selected team until expiry, replacement or withdrawal; traders do not need to adjust every possession.

| Planned Streamlit page | Purpose |
| --- | --- |
| Game Monitoring | Current game state, baseline forecasts and available timestamped market quotes |
| What-if Simulator | Adjust the five controls, compare outcome distributions, save or revoke scenarios |
| Research & Review | Retrieve cited evidence with RAG and retain adjustment rationale and review history |

Model validation is an auxiliary tab/report. Spark will reconstruct possessions from the 13,592,899 historical events and support distribution aggregation and batch simulation. Interactive queries will use cached distributions. Existing RDS and Atlas services will support operational records, with a separate Star warehouse and a persistent Qdrant index. Distributed performance will be measured rather than assumed.

[Earlier simulator plan — 20 November 2026](docs/planning/What_If_Simulator_Project_Plan_2026-11-20.html): retained planning history; page assignments and controls are superseded by the current proposal and AGENTS.md.

[Earlier next steps — 19 November 2026](docs/planning/Next_Steps_2026-11-19.html): the preceding monitoring/investigation proposal, retained as historical context.

Use [AGENTS.md](AGENTS.md) for the latest scope and priorities, the proposal for the product outline, and [data/metadata/README.md](data/metadata/README.md) for the data catalog.

Current handoffs (24 November 2026):

- [RDS-to-EMR-HDFS migration](docs/handoffs/2026-11-24-rds-to-emr-hdfs-migration.md): immediate pipeline task, constraints and validation checklist (English first, followed by the Chinese original).
- [Trader operational database and simulation warehouse](docs/handoffs/2026-11-24-trader-operational-database-and-simulation-warehouse.md): proposed normalized operational model and analytical warehouse design (English).

## Folder map

```text
README.md               Setup and working rules
requirements.txt        Python packages used by the current scripts
.env.example            Variable names only; no credentials
scripts/                Actual collection, import and data-processing scripts
data/
  raw/                  Original NBA SQLite (and downloaded PDFs when available)
  staging/              Captured injury-report text and early news summaries
  collected/            Timestamped batches, raw responses, CSVs and audit logs
  metadata/             Dataset catalog, field dictionary, SQLite schema and checksums
docs/
  requirements/         Course requirements
  proposal/             Current Word proposal, including architecture
  planning/             Earlier supporting plans; may lag actual data
  handoffs/             Dated task and design handoffs; implementation status is explicit
tests/                  Offline tests for existing data pipelines
AGENTS.md               Maintained project decisions and progress evidence
```

Data batch names and paths are preserved so source links and resume commands continue to work. Files named `before_export_fix` and failed collection logs are audit history, not recommended analysis inputs. `data/metadata/dataset_catalog.csv` identifies these explicitly.

## Start locally

Clone the source repository and run commands from its root:

```powershell
git clone https://github.com/BarryNiu-Wahaha/nba-sportsbook-market-intelligence.git
cd nba-sportsbook-market-intelligence
```

GitHub includes code, documentation, tests and `data/metadata/`. Raw datasets, collected responses, credentials and `release/` are excluded. Obtain data privately from the project owner and restore the documented paths before running scripts that read local data. GitHub does not host the 2.35 GB NBA SQLite database.

Use an existing Python environment, or create one. Run from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/look_at_nba_sqlite.py
```

`look_at_nba_sqlite.py` opens the original SQLite read-only and prints its tables, schemas and counts. It does not connect to RDS. The local data can be explored without credentials. These dependencies are not a lockfile; use the team's agreed environment for reproducible work.

## Data and metadata

Read [data/metadata/README.md](data/metadata/README.md) first. The catalog covers historical NBA tables, odds, Guardian articles, injury records, source text, mappings and collection audit files. It distinguishes observed sample dates from the intended three-year news window.

- One odds JSON element is one game at one collection time; expand bookmakers, markets and outcomes only when needed.
- Guardian articles are inside `payload.response.results` in the saved wrapper. `fields.bodyText` holds the body.
- Injury report text, original PDF files, article bodies and AI-written summaries are different evidence types. The current injury samples have text extracts, with no original PDFs downloaded.
- Keep game/player IDs as strings when loading CSVs or spreadsheets. Blank mappings mean unresolved, not zero.
- Historical NBA games end in 2023. Current 2026 odds/news cannot be forced onto historical game IDs.
- Build each forecast from information available at that replay state; final scores are evaluation outcomes. Keep entire games in chronological development/evaluation splits. Missing injury reports do not mean a player is healthy.

## Scripts

All commands below are run from the project root. There are no folder-organizing or packaging helper scripts in the handoff.

| Script in `scripts/` | Purpose | External requests / writes |
| --- | --- | --- |
| `look_at_nba_sqlite.py` | Inspect historical SQLite tables and counts | Read-only local SQLite |
| `build_injury_news_sample.py` | Build injury CSVs, mappings and source metadata from saved text | Offline; overwrites the existing derived injury sample |
| `collect_odds_to_mongodb.py` | Collect one snapshot, or import saved JSON with `--import-file` | Default: one Odds request + Atlas write. Saved import: no Odds request. Add `--dry-run` for offline preview |
| `collect_guardian_to_mongodb.py` | Collect one page into Atlas, resume a saved batch, or run local monthly backfill | Default: one page + Atlas write. `--resume`: no API request. `--backfill`: local JSON/CSV only; add `--plan` for offline preview |
| `download_injury_pdfs.py` | Download the three already-discovered injury PDFs | NBA PDF requests; local writes |
| `collect_odds_sample.ps1` | Earlier single-request odds collector and CSV exporter | Odds API request; local writes |
| `migrate_sqlite_to_rds.py` | Copy SQLite into a new RDS MySQL database | Creates a database and copies rows; migration already completed, not an onboarding step |

Safe offline previews:

```powershell
python scripts/collect_guardian_to_mongodb.py --backfill --plan
python scripts/collect_odds_to_mongodb.py --import-file data/collected/odds_mongodb_20261118T021208Z_ccbe3ddf/odds_raw.json --dry-run
```

Each collector is now self-contained. The former standalone odds importer and Guardian local collector have been merged into these two files and removed.

When collection/import is intended, use the appropriate mode:

```powershell
# One new odds snapshot -> local backup + Atlas
python scripts/collect_odds_to_mongodb.py

# Saved odds -> Atlas; no new Odds API request
python scripts/collect_odds_to_mongodb.py --import-file data/collected/odds_mongodb_20261118T021208Z_ccbe3ddf/odds_raw.json

# One Guardian page (default: 10 articles with bodies) -> local backup + Atlas
python scripts/collect_guardian_to_mongodb.py

# Saved Guardian MongoDB batch -> Atlas; no new Guardian request
python scripts/collect_guardian_to_mongodb.py --resume data/collected/guardian_mongodb_20261118T025946Z_e999017a

# Explicit local backfill with a one-request budget; does not write Atlas
python scripts/collect_guardian_to_mongodb.py --backfill --include-body --max-requests 1
```

Backfill retains the 2023-11-17 through 2026-11-17 date range and defaults to at most 100 requests per run unless overridden. Repeating the same backfill command reuses saved pages. `--resume` accepts a single-page MongoDB batch, not the monthly backfill directory.

Do not run every script as a setup checklist. Agree on collection budget before requesting more data. `--check-connection` on the Atlas collectors connects to Atlas and may create indexes.

## Configuration

`.env.example` lists the required variable names. The scripts read **process environment variables**, not `.env` files automatically. MongoDB collectors and importers prompt for a hidden URI if `MONGODB_URI` is unset. API collectors use `ODDS_API_KEY` or `GUARDIAN_API_KEY`; the monthly Guardian backfill requires its key in the environment. RDS scripts use `RDS_HOST` and `RDS_USER`, and prompt for the password.

Get credentials privately from the project owner. Do not put them in Python files, metadata, S3 handoff files or screenshots. The sharing package does not include AWS credentials or machine-specific editor settings.

## Sharing code and data

Share code through this GitHub repository. `.gitignore` excludes local data, credentials, environments, temporary files and the local release package. Markdown handoffs in docs/handoffs/ are included in Git. `.env.example` contains variable names only.

`release/draftkings-team/` is a separate local handoff package in the owner's workspace. Its `MANIFEST.csv` lists packaged files and SHA-256 hashes. It is not included in GitHub. Arrange data access privately with the owner; S3 is not required for this checkout and no S3 upload was performed as part of this publication. Metadata and checksums describe the collected snapshot, not files included in GitHub.

For implementation status and remaining work, use [AGENTS.md](AGENTS.md). This repository contains source code, documentation and metadata; it is not a deployed Streamlit/RAG application.
