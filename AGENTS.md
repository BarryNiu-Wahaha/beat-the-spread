# Repository Guidelines

本文件是 contributor guide、agent 执行指引和项目进度记录。最后核对：**2026-11-17，America/New_York**。当晚采集目录名中的 `20261118` 使用 UTC。

## Project Context & Sources of Truth

项目：**DraftKings Market Monitoring & Investigation Platform**，面向 sportsbook trading analysts，辅助比较赔率、调查相关信息和查找相似历史比赛。

- [The project requirement.txt](docs/requirements/The%20project%20requirement.txt)：课程要求与最终交付物。
- [DraftKings Project Proposal.pdf](docs/proposal/DraftKings%20Project%20Proposal.pdf)：主要 proposal。
- [DraftKings_Proposal_intro.pdf](docs/proposal/DraftKings_Proposal_intro.pdf)：分析师工作流、三页应用、引用与赛前信息约束。
- [Project_Next_Steps.docx](Project_Next_Steps.docx)、[News_Backfill.html](News_Backfill.html)：已有辅助文档，可能落后于最新采集结果。
- 用户最新决定和实际数据决定实施范围；proposal 是可调整的样板。不要反复纠正草案措辞而阻碍实施。

目标应用包含三个部分：

1. **Market Monitoring Dashboard**：比较同一比赛、市场、结果的 DraftKings 与其他博彩公司赔率，显示差异及报价时间。
2. **AI Research Assistant**：检索伤病报告、新闻、球队动态，回答问题并提供来源、时间与证据片段。
3. **Similar Game Finder**：基于历史赛前特征做 KNN，展示相似比赛和最终分差背景。

平台辅助人工调查，不自动调整赔率；新闻相关性不证明赔率变化的因果。当前实际赔率样本只有 `h2h` / moneyline，不能把 proposal 的 spread 示例写成已采集能力。

## Assignment Requirements & Status

| 必须满足的要求 | 当前状态与剩余工作 |
| --- | --- |
| 至少一个真实数据集超过 100 万条 | 本地 NBA play-by-play 有 **13,592,899** 条，满足规模要求；新闻/RAG 不需要百万篇。 |
| RDBMS operational data | 用户已确认 NBA 数据迁入 RDS；alerts / investigations 等应用操作记录仍待实现。历史数据迁移不等于完成全部 operational 功能。 |
| NoSQL data | Atlas 已有赔率和新闻成功写入记录；伤病资料的云端入库仍待完成。 |
| Hadoop/HDFS 和/或 Spark | 尚未实现；计划用 Spark 处理历史 NBA 大数据及赛前特征。 |
| ETL/ELT → Star/Snowflake warehouse | 尚未实现；需落实事实表、维度表、粒度和加载流程。CSV 导出不算完成仓库。 |
| Streamlit analytics | 三个页面尚未实现。 |
| RAG：embeddings + vector database | 尚未切块、生成 embedding、建立 ChromaDB/Qdrant 索引或接通聊天。MongoDB 正文入库不等于 RAG 完成。 |
| AWS working application | 用户已使用 RDS；应用、向量服务、持久化与 production URL 尚未交付。Atlas 的 provider/region 未在本次核对。 |
| 最终交付 | 工作系统、production URL、报告、视频、代码、课堂展示；每位成员都须理解完整架构。 |

S3、Redshift、EMR 不是 TXT 指定必须使用的产品，不要仅因 proposal 提到就购买或部署。

## Current Decisions

- 历史 NBA 数据可以用旧年份。**用户已确认 RDS 连接及迁移完成，不要重新迁移或当成未开始。**
- 新闻目标范围：**2023-11-17 至 2026-11-17**。目前只有样本，三年回填尚未完成；不要静默改成最近七天。
- 当前新闻来源是 Guardian；proposal 的 GDELT 方案未实施。Guardian 不保证覆盖每个球员、比赛或正式伤病状态。
- **暂时不接 S3**。新闻正文直接存入已有 Atlas 集群的 `nba_project.news_articles`，赔率存入 `nba_project.odds_snapshots`；优先复用已有集群。
- Atlas 是托管平台，cluster 是部署，database 是 `nba_project`，collection 是 `news_articles` 等。不要称作 AWS 自有的“Amazon MongoDB”。
- 使用现有样本开发 dashboard/RAG，不持续轮询。页面刷新应读数据库，不能每次交互都请求外部 API。
- Atlas 实际剩余空间尚未测量。先测正文、索引与已有数据占用，再决定扩容；不要保证三年所有资料装得下，也不要自动迁往 EC2。

## Verified Progress — 2026-11-17

证据级别：本地原文件和状态日志可核对；云端写入结果来自用户成功运行时生成的日志。本次文档整理没有重新连接 Atlas/RDS，也没有请求外部数据或写库。

| 部分 | 已完成与证据 | 限制 |
| --- | --- | --- |
| NBA 原始库 | 本次只读核对 `data/raw/nba.sqlite`：16 张表；game **65,698** 条；play_by_play **13,592,899**；player **4,815**；team **30**。 | game 日期实际为 **1946-11-01 至 2023-06-12**，不能把 proposal 的年份当成已验证事实。 |
| RDS | 用户确认已连接并完成迁移；脚本为 `scripts/migrate_sqlite_to_rds.py`。 | 本次未重新检查云端全部行数、索引与键约束。 |
| 首批赔率 | `data/collected/odds_sample_20261118T0022108258385Z/`：9 场、118 条展开赔率、9 家博彩公司；保留原始 JSON。 | PowerShell 嵌套数组曾使 CSV 出现 `System.Object[]`；已修复脚本并从原始 JSON 重建 CSV，错误导出另存备份。 |
| Atlas 赔率 | `data/collected/odds_mongodb_20261118T021208Z_ccbe3ddf/collection_status.json`：completed；14 场、插入 14、验证 14。 | 该次请求扣 1 credit，当时返回剩余 499；不是当前实时余额。 |
| Atlas 新闻 | `data/collected/guardian_mongodb_20261118T025946Z_e999017a/`：completed；10 篇、10 篇有正文、插入及验证均为 10。原始 JSON 已核对。 | NBA 标签、约定三年范围、newest、第 1 页、每页 10；当时 API 匹配总数 **389**、39 页。389 不是已下载数，也不是全网 NBA 新闻总量。 |
| 伤病样本 | `data/staging/injury_reports/` 有 3 份官方 PDF 的网页提取文本；`data/collected/injury_news_2026-11-17/` 有 124 条伤病记录、67 条球队提交状态、25 个本地比赛映射和 1 个状态变化。 | 原始 PDF 本地下载数仍为 0；50 个唯一球员名未匹配。该批次的 8 条早期新闻索引/摘要不是 Guardian 的 10 篇正文。 |
| 测试 | `python -m unittest discover -s tests -v`：**19 项通过**。 | 主要为离线/模拟边界测试，不证明当前云端可达；一次运行出现模拟 HTTPError 的清理 ResourceWarning，未导致失败。 |

保留旧失败日志，但以之后的成功记录判断进度：曾出现本地网络访问失败、MongoDB preflight OperationFailure；后者 request_attempts=0，未请求 Odds，用户之后已成功跑通。

## Project Structure & Module Organization

- `data/raw/nba.sqlite`：原始 SQLite，只读保留。
- `scripts/look.py`：查看表结构及行数；`connect.py`：探索并向 MySQL 写小样本，使用 `test_` 前缀。
- `scripts/migrate_sqlite_to_rds.py`：迁移到新的 RDS MySQL database 并核对行数；不要为了测试采集流程重跑。
- `scripts/collect_odds_to_mongodb.py`：MongoDB 预检 → 单次 NBA/us/h2h 请求 → JSON 备份 → 比赛快照入库。
- `scripts/import_odds_to_mongodb.py`：从已保存 JSON 补传赔率，无需再次请求 Odds。
- `scripts/collect_guardian_to_mongodb.py`：单页新闻正文入库；支持 `--resume` 补传，不接 S3。
- `scripts/collect_guardian_news.py`：按月分页的历史新闻本地回填；默认最多 100 请求，不要无预算直接运行。
- `scripts/build_injury_news_sample.py`：离线生成伤病样本、来源、实体及比赛映射。
- `scripts/download_injury_pdfs.py`：仅下载已发现的 3 份 PDF 队列，不是三年历史报告采集器。
- `scripts/collect_odds_sample.ps1`：早期单次赔率采集及 CSV 导出，原始 JSON 仍保留。
- `data/collected/<batch>/`：原始响应、派生数据及状态日志。`data/staging/`：当前报告提取文本和早期新闻种子。
- `tests/`：Python unittest 离线测试。根目录 PDF/PNG 为 proposal 和架构材料；`Wyatt Walsh.pdf` 当前为空文件。

## Build, Test, and Development Commands

从仓库根目录执行；如果当前位于 `scripts/`，去掉命令中的 `scripts/`。优先使用用户现有 `msba` 环境。新机器可先用 `python -m venv .venv` 创建环境。

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall scripts
```

没有统一 build、formatter、linter 或 dependency lockfile。语法检查不能代替数据库行为验证。

仅检查 Atlas（会检查/创建查询索引，不请求新闻或赔率 API）：

```powershell
python scripts/collect_odds_to_mongodb.py --check-connection
python scripts/collect_guardian_to_mongodb.py --check-connection
```

用户需要新增采集时再执行；以下命令会请求外部 API 并写入云端：

```powershell
python scripts/collect_odds_to_mongodb.py
python scripts/collect_guardian_to_mongodb.py --start 2023-11-17 --end 2026-11-17 --page-size 10 --page 1
```

失败后复用原始文件，避免重新消耗请求。下面第一条仅离线预览，移除 `--dry-run` 才写库；第二条直接补传 MongoDB，不请求 Guardian：

```powershell
python scripts/collect_odds_to_mongodb.py --import-file data/collected/odds_mongodb_20261118T021208Z_ccbe3ddf/odds_raw.json --dry-run
python scripts/collect_guardian_to_mongodb.py --resume data/collected/guardian_mongodb_20261118T025946Z_e999017a
```

探索旧数据时，先 `Set-Location data/raw` 再运行 `python look.py`。`connect.py` 会写 MySQL；迁移脚本会创建目标库，执行前核对目标及用户授权。

## Coding Style & Testing Guidelines

使用 4 空格缩进、函数/变量 `snake_case`、常量 `UPPER_SNAKE_CASE`。Python 文件名清晰，使用简短 docstring、script-relative paths 和 `main()`。保持代码让初级数据分析师也能读懂，避免无必要的框架和抽象。

使用标准库 unittest，命名 `tests/test_*.py`，暂无 coverage 门槛。测试临时文件和模拟 API/数据库，不使用真实 key 或真实 Atlas 写入。验证关键行为：单次请求、连接失败不耗 API、原文保留、稳定 ID、去重、日期边界、断点补传和缺失正文。

迁移变更用小 SQLite fixture 和独立可丢弃 MySQL 库验证：表名、行数、字段、空表与代表性数值。不要为纯文档变更新增无意义测试。

## Commit & Pull Request Guidelines

当前目录没有 Git 元数据，无法推断历史 commit 风格。使用简短祈使句，例如 `Validate migration row counts`。PR 说明问题、改动、验证和数据库影响；关联 issue（如有）。不要为了写进度文档擅自初始化或发布仓库。

## Data & Configuration Safety

- 不提交凭据或数据库导出。新代码使用 `MONGODB_URI`、`ODDS_API_KEY`、`GUARDIAN_API_KEY` 环境变量或隐藏输入，日志不打印秘密。
- **实际待办**：当前 `collect_odds_to_mongodb.py` 和 `collect_guardian_to_mongodb.py` 含直接赋值的 MongoDB 连接串。不要打印、复制或写进文档；后续整理应移回环境变量/隐藏输入。本次仅更新文档，没有改用户修改的采集脚本。
- 保留原始 SQLite、JSON、PDF/提取文本和来源时间。失败与成功分别记录，不伪造完成状态。
- Odds 默认单次 NBA/us/h2h 请求，不自动重试或启动 scheduler；Guardian 使用独立 key/额度，默认单页 10 条。扩大采集前明确预算。
- 迁移只复制字段和数据，不完整复制索引、键、默认值、视图或触发器；失败可能留下部分数据，遵循迁移脚本的新目标库策略处理。

## Data Modeling & RAG Instructions

- **赔率**：一场比赛的一次采集快照是一条文档；保留 `raw.bookmakers[].markets[].outcomes[]`。不同采集时刻独立保存，同一快照补传不重复。
- **新闻**：一篇文章一条文档，按来源文章 ID 去重；正文、URL、发布时间、采集时间和标签一起保存。旧批次不能覆盖更新的内容；`rag_ready` 目前只表示有正文，不代表已向量化。
- **伤病**：保留报告时间、比赛、球队、球员、状态、原因。`not submitted` 或未列入报告不能解释成健康/可出场。
- **Metadata**：保留 source、源 ID、本地 ID、URL、发布时间及获取时间。球队/球员/比赛映射必须可追溯；2026 新闻和赔率可能无法匹配截至 2023 的历史库，未匹配项留空，不能强行关联。
- **赛前时点**：KNN 特征只使用开赛前已知信息；历史调查按相应时点过滤新闻、伤病和赔率，不使用最终赛果构造该场赛前特征。
- **RAG**：正文/报告文本 → 语义切块 → embedding → ChromaDB 或 Qdrant。片段保留文档 ID、URL、报告时间、球队/球员，以及可获得的 PDF 页码。
- 检索后把原文片段交给模型并引用来源；官方状态与媒体解释分开。精确统计、报价和状态优先结构化查询；缺乏证据时说明缺失。
- Guardian 是单一媒体来源，不保证完整覆盖。链接、AI 短摘要和原文不是同一种证据；新增来源时核实访问及使用条件，不承诺未经确认的全文/历史覆盖。

## Next Work — Recommended Order

1. 整理凭据配置；检查已入库的 10 篇新闻正文是否适合目标问题，测量 Atlas 数据和索引占用。
2. 补充官方伤病 PDF 原件、解析及 Atlas 入库；现有 3 份提取文本可以先用于开发，记录历史日期缺口。
3. 在明确预算下继续 Guardian 分页并去重、记录覆盖率。389 是此次查询当时的匹配数，后续可能变化。
4. 建立 metadata 和小型 RAG：正文 → chunks → embeddings → 持久化向量库 → 带引用问答；用代表性问题验证时间过滤与检索，再扩量。
5. 实施 Spark 历史特征、Star/Snowflake warehouse、RDS alerts/investigations、KNN 和 Streamlit 三个页面。
6. 集成并部署 AWS 应用及持久化服务，验证 URL、重启后数据保留和日志，完成报告、视频与团队演示。

S3 和迁移 MongoDB 到 EC2 均延后；只有用户改变决定或实际测量表明需要时再规划。

## Team Handoff ? 2026-11-19

- ????????????????????? S3???????????/???????????????? metadata????????????????????????????/??????
- ?????`START_HERE.html`?`README.md`??????proposal ????????? `docs/requirements/`?`docs/proposal/`?`docs/planning/`??????????
- `data/metadata/`?30 ???/???????390 ? CSV/JSON ???????16 ? SQLite ?? 341 ???????? SQL ????? SHA-256????????????????????????????????
- ?????????? `connect.py` ????????????????????????? `MANIFEST.csv`??????????????????????
- ?????? Guardian wrapper?`payload.response.results` ? 10 ??????? **2026-10-28T19:25:28Z ? 2026-11-15T01:26:32Z**?????????????
- ?? NBA SQLite ? **2,349,588,480 bytes**???????????????? `data/metadata/sqlite_tables.csv`?????????????
- ???`D:/Miniconda3/envs/msba/python.exe -m unittest discover -s tests -v` **19 ???**??????????????????????????????
- ??? Word ?????? `data/raw/migrate_sqlite_to_rds.py` ???? Windows ????????????? `docs/planning/` ? `scripts/` ????????????????
- ???? `release/draftkings-team/` ?????????????? 63 ????? manifest????????????? 2.35 GB??????? 19 ?????????HTML ????? 30 ?????????????????????????????? `.local`??????????Office ??????????????? SHA-256 ?????? `MANIFEST.csv`?????????? metadata ??????

## Collector Consolidation ? 2026-11-19

- ??????? SimpleDS/readable-data-science ????????? `scripts/` ? 8 ????????? Guardian ????????????????????
- ????? `import_odds_to_mongodb.py` ? `collect_guardian_news.py`???????????? `--import-file JSON [--dry-run] [--captured-at TIME]` ???Guardian ??????? Atlas?`--resume BATCH` ???`--backfill` ???????`--backfill --plan` ??????????? Atlas?
- ?? API ?????????????????????? ID?????????????????????????????????????????????? API?????????????
- ???24 ??????????? 5 ??????????????????????????????? ID?Guardian ???? fixture ??????????JSON/CSV/coverage???????
- README??????????????????????????? 62?? `MANIFEST.csv`??????? metadata ???????

## Agent-Specific Instructions

- 用户说 `simple ds` 时使用 readable-data-science skill；说 `grill me` 时使用 grilling skill。
- 默认中文解释，保留必要英文术语；写简单、可追踪的 Python。普通计划按用户偏好用简洁说明、HTML 或 Word；本文件是明确要求的 Markdown 指令和进度记录。
- 先查当前脚本和最新 collection_status.json，再报告状态。区分“代码存在”“离线测试通过”“用户运行成功”“当前云端重新验证”。
- 在已有授权内直接推进准备、可逆修复和离线验证，不重复询问已确认事项。新增付费资源、持续采集或扩大量级不属于默认授权。
- 继续维护**本文件**，不要另建 agent.md 或重复的项目状态文档。实质工作完成后更新日期、证据路径、状态及下一步；不记录凭据或未验证的完成声明。


## GitHub publication preparation ? 2026-11-19

- Target: https://github.com/BarryNiu-Wahaha/nba-sportsbook-market-intelligence (`main`). Preserve the existing remote README commit as the parent of the project commit.
- Existing `.gitignore` and `.env.example` checked. Publish code, docs, tests and `data/metadata/`; exclude raw/staging/collected data, database files, credentials, local helpers and release packages.
- Pre-publication scan of 31 candidate files (including PDF and DOCX text) found no credential-pattern matches or literal Python credential assignments. Earlier notes about hard-coded collector credentials are historical; current collectors use environment variables / hidden input.
- Verification: `D:/Miniconda3/envs/msba/python.exe -m unittest discover -s tests -v` passed all 24 offline tests. This does not verify current cloud connectivity.
- README startup instructions now use GitHub and the existing `scripts/look_at_nba_sqlite.py`; data access is separate. No S3 upload, API collection or database migration performed.
- Remove temporary publication helper scripts after use. Verify remote main matches local HEAD after pushing; push success is not asserted by this preparation entry.
