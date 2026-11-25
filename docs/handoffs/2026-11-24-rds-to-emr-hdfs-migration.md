# NBA 历史数据：RDS → EMR HDFS 迁移交接 Note

- 创建时间：2026-11-24 20:53:05 EST（America/New_York，UTC−05:00）。
- UTC 时间：2026-11-25 01:53:05 UTC。
- 名称：RDS-to-HDFS 历史数据 Pipeline — 下次访问与检查清单。
- 整理者：Codex；需求与技术路线由项目用户确定。
- 状态：需求已记录；迁移代码、EMR 运行及云端验证尚未完成。
- 本次范围：按用户后续要求保存交接 note，更新项目指引；本次不执行迁移。

## 1. 下次从这里开始

先阅读根目录 [AGENTS.md](../../AGENTS.md)，再阅读本 note。产品最终目标仍为 NBA 比赛监控与 What-if 平台，但当前优先级改为建立可靠的历史数据存储和 Spark 数据访问 Pipeline。

确定路线：

```text
现有 AWS RDS MySQL（保留原始数据）
    → Spark JDBC
    → Parquet 文件
    → AWS EMR on EC2 的 HDFS
    → PySpark / Spark SQL 探索
```

路线与当前任务目标一致。验收重点是可重跑、数据保真、失败可恢复和有实测证据；不能仅以成功写出文件判断完成。

本阶段不开发 Monte Carlo Simulator、Streamlit Dashboard、Star/Snowflake warehouse 或 RAG。Possession Reconstruction 是后续使用场景，本轮先打通原始数据访问。

## 2. 已确定的边界

- 学校环境限制为 **1 Primary Node + 1 Core Node**，使用 AWS EMR on EC2。
- 使用 PySpark、HDFS、Parquet；不额外引入 Sqoop、Hive、Pig、Kafka 或 S3。
- 不创建新的收费 AWS 资源；复用用户已有且允许访问的资源。
- 按用户给定单 Core Node 拓扑，数据块在同一存储 Worker 上；可以利用单机多核并行，不能声称跨 Worker 分布式存储或计算。实际 DataNode 和 executor 布局仍须检查并记录。
- HDFS block 分配由 HDFS 管理，不手动切块。JDBC 读分区、Spark 写分区、HDFS block 是三个不同层面。
- EMR terminate 后 HDFS 数据可能丢失。RDS 原始数据必须保留，迁移流程必须能够重建 HDFS 数据。
- 原始重复记录、异常字段、空值等只记录，不在迁移阶段清洗、去重或删除。

## 3. 已有证据与未验证内容

| 项目 | 已有证据 | 尚未验证 |
| --- | --- | --- |
| 原始数据 | 2026-11-24 本地只读核对 SQLite：16 表、2,349,588,480 bytes；play_by_play 13,592,899 行 | 当前 RDS 逐表实际规模与 schema |
| RDS | 用户此前确认 SQLite → RDS 迁移完成；现有迁移脚本保留 | 当前连接、权限、索引、服务版本及负载 |
| 字段映射 | 现有迁移脚本将 TEXT 映射为 LONGTEXT，未复制索引/键等 | 云端是否后来调整过字段或索引 |
| 探索 SQL | scripts/explore_nba_source.sql 已存在；13 条数据查询此前通过本地字段/查询计划核对 | MySQL 线上执行结果及性能；Spark SQL 适配 |
| 离线测试 | 2026-11-24 原有采集器 24 项测试通过 | 这些测试不覆盖新 Pipeline；新测试待编写 |
| EMR/HDFS | 用户确定部署方式及学校节点限制 | Cluster ID、运行状态、版本、网络、容量、DataNode 布局、JDBC driver |
| 迁移/性能 | 尚无本任务执行证据 | Parquet、完整性报告、HDFS block 位置和性能结果均待生成 |

原始库属于历史 source database；HDFS raw 层也不等于已经完成课程要求的 warehouse。

已有参考路径：

- [RDS 迁移脚本](../../scripts/migrate_sqlite_to_rds.py)：只参考配置与字段映射，不重跑历史迁移。
- [MySQL 探索 SQL](../../scripts/explore_nba_source.sql)。
- [表规模](../../data/metadata/sqlite_tables.csv)、[字段信息](../../data/metadata/sqlite_columns.csv)、[数据解释](../../data/metadata/README.md)。
- [.env.example](../../.env.example)、[requirements.txt](../../requirements.txt)。

## 4. 下次访问的检查顺序

### A. Repository 与环境

- [ ] 阅读 AGENTS.md、现有脚本、配置模板、metadata 和 Git 状态，保留用户未提交修改。
- [ ] 确认已有 EMR Cluster ID、AWS Region、EMR release、Spark/Hadoop/Java/Python 版本。
- [ ] 确认允许的 SSH/提交作业方式、执行用户、YARN 资源与 HDFS 目录权限。
- [ ] 检查 Primary/Core 实际角色、DataNode 数量、磁盘可用空间、block size 和 replication 配置。
- [ ] 检查 RDS endpoint、端口、实际数据库名、只读权限、TLS、VPC/subnet/security group/DNS 可达性；不把密码写进 note、命令参数或日志。
- [ ] 确认 Spark driver/executor 均可访问 RDS，且兼容的 MySQL JDBC driver 可用；不默认下载成功或已安装。

### B. RDS 元数据与读取方案

- [ ] 读取当前 RDS 的全部目标表、列顺序、类型、NULL 属性和索引，与本地 16 表清单比较；不盲目迁移其他业务 schema。
- [ ] 记录逐表行数和读取开始时间，确定源数据在迁移/验证期间是否保持不变。
- [ ] 如源表会变化，先确定一致性策略；多条 JDBC 连接不能直接当作共享同一个数据库快照。
- [ ] 特别检查 game_id 的文本类型、前导零、带 .0 的 ID、日期文本及已有重复 game_id。
- [ ] 检查索引和执行计划后决定 JDBC 分区。无合适索引时先评估串行批量读取，避免多个谓词并行造成重复全表扫描。
- [ ] 分开配置 JDBC fetch size/并发与 Spark 写分区。play_by_play 写出 4 partitions 只是初始试验值，根据实际资源、压缩后大小和耗时调整。

### C. 本地准备与 EMR 实施

- [ ] 编写简单 Python 迁移脚本、探索脚本和必要离线测试，复用 RDS_HOST/RDS_USER 等已有配置方式。
- [ ] 先用小表验证连接、类型映射、Parquet 读写和状态报告，再扩大到 play_by_play 和全部 16 表。
- [ ] 明确已完成、未完成、失败、重试和重新迁移的处理规则；默认拒绝覆盖已有目标数据。
- [ ] 设计每次运行的独立 staging/run 标识，验证通过后才发布对应表；部分写出不得标记为成功。
- [ ] 不能仅凭目标目录存在就跳过；检查 manifest、源标识及验证状态。不自动删除失败目录或已验证数据。
- [ ] 交付用户可在 EMR 执行的具体命令；用实际环境填入参数后再运行，不伪造云端验证。

目标布局示例（待实际写出）：

```text
/nba/raw/game/part-*.parquet
/nba/raw/team/part-*.parquet
/nba/raw/player/part-*.parquet
/nba/raw/play_by_play/part-*.parquet
...其余 12 张表各一个目录
```

## 5. 迁移验收清单

- [ ] 16 张表分别记录：源表、目标路径、run ID、状态、行数、Parquet 数据文件数量、文件大小和耗时。
- [ ] 对比 RDS 与读回 Parquet 的行数；空表也应保留 schema 并正确报告。
- [ ] 保存 MySQL → Spark → Parquet 类型映射，验证字段名称、顺序、值与逐列 NULL 数；不把不同系统的类型名称相同作为唯一判据。
- [ ] 核对 game_id 前导零和字符串长度，确保没有数值转换造成的损失。
- [ ] 验证原始重复记录的重数保留；行数相等本身不能排除等量丢失/重复。确定可执行的内容校验及其限制，区分抽样、摘要与完整比较。
- [ ] 读回全部 Parquet 数据验证可读取性；记录失败文件和未完成表。
- [ ] 实测 HDFS block 数量、replica 状态和 DataNode 位置，与文件数分开报告。
- [ ] 记录源数据已有质量问题，例如同一 game_id 的 All-Star / All Star 版本；不在本轮修复。
- [ ] 把报告与运行配置保存到集群之外的现有允许位置，避免只留在可能被 terminate 的 HDFS；不额外引入 S3。

## 6. Spark SQL 与性能比较

探索脚本直接从 HDFS 读 Parquet，注册 session 内 Temporary Views，不要求 Hive：

```python
df = spark.read.parquet('hdfs:///nba/raw/play_by_play')
df.createOrReplaceTempView('play_by_play')
```

- [ ] 从已有 SQL 中适配 SELECT、WHERE、GROUP BY、ORDER BY、JOIN、COUNT；MySQL metadata 查询不能原样用于 Spark。
- [ ] 包含单场比赛 `game_id = '0029600012'` 的事件探索，按 period/eventnum 查看；检查重复 game_id，避免 JOIN 膨胀。
- [ ] 同一数据范围、相同查询语义和结果校验下比较 MySQL 与 Spark SQL。
- [ ] 强制实际执行查询并消费结果，避免把 Spark lazy evaluation 的构造时间当查询耗时。
- [ ] 记录首次与重复运行、缓存状态、重复次数、数据规模、资源配置、MySQL 索引和查询计划；说明 Spark 启动时间是否计入。
- [ ] 报告实测时间及差异原因，不预设 Spark 更快，不把单 Core Node 当作多 Worker 加速证据。

## 7. 预期交付物与状态

| 交付物 | 当前状态 |
| --- | --- |
| RDS-to-HDFS Python 迁移脚本 | 待实施 |
| HDFS Parquet / Spark SQL 探索脚本 | 待实施 |
| 离线 fixture 与关键失败/重跑测试 | 待实施 |
| EMR 配置与具体运行命令 | 待环境核对后编写 |
| 逐表迁移与完整性验证报告 | 待实际执行；不得把模板填成成功 |
| MySQL/Spark SQL 实际性能报告 | 待实测 |
| 本交接 note 与 AGENTS.md 当前阶段更新 | 本次文档交付 |

下次可直接使用的提示：

> 阅读 AGENTS.md 和 docs/handoffs/2026-11-24-rds-to-emr-hdfs-migration.md，继续准备 RDS → Spark JDBC → Parquet → HDFS → Spark SQL Pipeline。先检查代码与可访问环境，完成本地代码和离线测试，再给出 EMR 具体执行命令；明确未验证事项，不创建收费资源，不修改 RDS 数据，不开发模拟器/UI/warehouse/RAG。
