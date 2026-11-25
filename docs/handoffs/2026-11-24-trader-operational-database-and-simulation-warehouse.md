# Trader Operations and Simulation Warehouse — Handoff

- Created: 2026-11-24 21:02:07 EST (America/New_York, UTC−05:00).
- UTC: 2026-11-25 02:02:07 UTC.
- Prepared by: Codex, based on the project owner's requirements and design discussion.
- Status: conceptual handoff; no database schema, ETL, or application implementation has been completed for this design.
- Purpose: preserve the operational database proposal and the direction for a warehouse tailored to the simulation workflow.

## 1. Project context and scope

Read [AGENTS.md](../../AGENTS.md) first. The product is an NBA Game Monitoring and What-if Simulation Platform for sportsbook traders and trading analysts. Its three planned pages are Game Monitoring, What-if Simulator, and Research & Review.

The current NBA historical database serves as an analytical source. Its existing tables do not record our traders' daily work. Whether it is called a historical warehouse or a source database, it does not by itself establish the new application's operational data workflow.

We propose a separate operational schema in the existing RDS MySQL deployment for genuine user actions: creating scenarios, submitting parameter versions, requesting simulations, activating adjustments, withdrawing them, and reviewing decisions.

The user also wants a warehouse tailored to the simulation. That warehouse would derive analytical facts from historical possessions, operational records, and simulation outputs. It would use a separate analytical schema and would not replace the operational database.

The immediate implementation priority remains the [RDS-to-EMR-HDFS pipeline](2026-11-24-rds-to-emr-hdfs-migration.md). This handoff does not authorize new paid resources or advance operational/warehouse implementation ahead of that task.

## 2. What is established versus proposed

| Item | Status |
| --- | --- |
| Use real trader adjustments and daily activities as operational data | User-requested direction |
| Use normalization and integrity constraints for operational records | User-requested direction |
| Derive a warehouse tailored to the simulation workflow | User-requested direction |
| Preserve original historical data and existing duplicates during migration | Established project constraint |
| Separate submission position from effective possession boundary | Required by the existing possession-boundary simulation design |
| Table names and fields below | Proposed, not approved DDL |
| One active adjustment version per session and target team | Recommended first-version rule; not yet confirmed |
| Direct activation versus approval before activation | Open business decision |
| Physical schemas, type mappings, ETL and deployment | Not implemented or verified |

## 3. Example daily workflow

1. Alice opens a replay session for a historical Lakers–Suns game.
2. During possession 150, she proposes higher three-point sampling weight and a faster pace preference.
3. She creates scenario version V7 with three-point weight 1.20 and pace weight 1.10, records a reason, and requests a baseline/scenario comparison.
4. Running a comparison does not automatically activate the adjustment.
5. If she chooses to keep it active while possession 150 is already in progress, the system schedules it for the next confirmed possession start, such as possession 151.
6. Subsequent forecasts apply the active relative weights to the baseline appropriate to each new state.
7. The adjustment ends at its specified expiry, is explicitly replaced, or is withdrawn. The history remains available.

These values change sampling weights; they do not promise a proportional change in realized event frequencies. The parameter definition must specify how each control affects sampling.

## 4. Time, possession, and session semantics

Store both wall-clock timestamps and basketball positions:

| Concept | Meaning |
| --- | --- |
| Submitted at | UTC timestamp of the user action |
| Observed position | Replay position the trader was viewing when submitting, possibly mid-possession |
| Effective from | First confirmed possession boundary at which the version may apply |
| Requested expiry | User instruction, such as end of period or an explicit boundary |
| Actual effective until | Boundary from which the version no longer applies, when resolved |
| Session | One independent replay or shared game workspace |

Use an inclusive start and exclusive end for boundary-based validity: `[effective_from, effective_until)`. Store requested expiry separately when the exact future boundary is not yet known. Record cancellation of a pending activation even if it never became effective.

Submission timestamps alone cannot identify the basketball state. Period and game clock alone are also insufficient because multiple events can share the same clock value.

The raw dataset has no ready-made possession ID. Do not treat eventnum as a possession ID. Reconstructed possession references must identify their game and reconstruction/data version. An observed mid-possession location needs a source event reference or equivalent replay cursor; it must not be mislabeled as a confirmed checkpoint.

Session scope matters: two people replaying the same historical game independently must not overwrite each other's adjustments. Rewinding within a session also needs an explicit policy before implementation; a new replay branch/session is one possible approach, not an agreed rule.

## 5. Proposed normalized operational model

Names below describe responsibilities rather than final DDL.

| Table | One row represents | Example attributes |
| --- | --- | --- |
| trader | One application user | trader_id, display_name, role |
| game_session | One replay or game workspace | session_id, game reference, data version, creator, status |
| session_checkpoint | One confirmed possession-start state in a session | checkpoint_id, session_id, sequence, possession reference, period, clock, scores, offense |
| scenario | One hypothesis for a session and target team | scenario_id, session_id, target_team_id, creator |
| scenario_version | One immutable revision of that hypothesis | version_id, scenario_id, version_number, author, submitted_at, observed position, reason |
| adjustment_parameter | One supported control definition | parameter_code, name, unit, definition/version reference |
| adjustment_value | One control value in one version | version_id, parameter_code, weight_value |
| activation | One activation interval or pending instruction for a version | activation_id, version_id, requested/effective start, expiry, actual end, status |
| simulation_run | One execution request | run_id, checkpoint_id, model version, seed, budget, status, start/end timestamps |
| run_adjustment | One version actually used by one run | run_id, version_id |

The five controls are three-point frequency, two-point frequency, turnover tendency, pace, and free-throw frequency. Specify whether omitted values mean neutral weight or whether all five are required; do not leave this implicit.

Operational checkpoints support concrete actions and reproducible runs. They do not require copying every raw event into the operational schema. Baseline runs may have no run_adjustment entries. A comparison must explicitly associate its baseline and adjusted runs through a comparison identifier or equivalent relationship; its final table design remains to be decided.

Activation, replacement, withdrawal, and any approval need actor/time/reason history. The tables above are a starting model, not a claim that a mutable status column alone provides an audit trail. Decide the minimal action-history/review records when the approval policy is settled.

## 6. Normalization and integrity

Aim for third normal form by identifying functional dependencies, not simply by increasing table count:

- Trader identity details belong in trader, rather than being repeated on each adjustment.
- Version author, submission time, and rationale belong to the version, not every parameter row.
- Parameter definitions belong in adjustment_parameter; version-specific values belong in adjustment_value.
- Enforce uniqueness of `(scenario_id, version_number)` and `(version_id, parameter_code)`.
- Enforce uniqueness of checkpoint sequence within its session and explicitly define the referenced reconstruction version.
- Use primary/foreign keys to prevent references to missing sessions, versions, and runs.
- Validate weights against the relevant parameter definition. Validate that effective boundaries belong to the right session and occur in the correct order.
- Submitted versions are immutable. Editing creates a new version; prior runs keep their original version references.
- Treat replacement/withdrawal as recorded business actions, not deletion of historical rows.

Five fixed weight columns on scenario_version can also satisfy 3NF. The parameter-detail alternative is proposed for explicit definitions and extensibility, not because fixed columns would inherently violate normalization.

Some rules need transactional application logic in addition to foreign keys. For example, preventing two overlapping active adjustments requires concurrency control; a simple unique key on a start timestamp is not enough. The recommended initial policy is one active version per session and target team, with explicit replacement rather than silent multiplication of competing weights.

Logical game/team references must use canonical validated identities. Raw game_id duplicates mean the raw game table cannot automatically serve as a unique foreign-key parent. Do not delete source duplicates merely to make constraints pass.

## 7. Relationship to Atlas and daily operations

RDS should hold authoritative structured workflow state, immutable parameter versions, execution requests, and lifecycle relationships. Atlas can retain richer rationale/evidence/research/review document revisions, consistent with the existing project plan.

Use stable document IDs and revision references across stores. Decide which store owns each field; do not create two independently editable authoritative copies of the same rationale. A short operational reason and a referenced detailed evidence document can have different roles.

Cross-store writes need idempotency, visible pending/failure status, and recovery. Do not assume an atomic transaction spans RDS and Atlas.

The course demonstration should generate records through real application actions: create a scenario, run a comparison, activate, revise, and withdraw it. Demonstration actions must be labeled as project/replay activity, not actual DraftKings operations.

## 8. Proposed warehouse tailored to simulation

The warehouse answers analytical questions across sessions, scenarios, runs, and historical games. It is separate from the normalized operational schema and from HDFS raw storage.

```text
Historical NBA source → HDFS raw Parquet → validated reconstructed possessions
                                                      ↓
Trader operational records + simulation outputs → versioned ETL → analytical schema
```

Proposed fact grains:

| Fact | Exact proposed grain | Example measures/purpose |
| --- | --- | --- |
| fact_possession | One accepted historical possession per reconstruction version | Points, elapsed game-clock time, shot/FT/turnover counts and quality flags |
| fact_simulation_run | One run at one starting checkpoint and one scenario configuration | Simulations completed, duration, final-margin/total summaries, win probability, error status |
| fact_simulation_histogram | One run × metric × bin specification × bin | Count/proportion of simulated outcomes; bins require versioned edges/meaning |
| fact_adjustment_action | One recorded operational action | Analyze submission, activation, replacement, withdrawal and approval activity |
| fact_baseline_evaluation | One baseline run at one evaluated checkpoint | Forecast and observed outcome needed for calibration, scoring and error analysis |

Proposed dimensions include date/time, game, team, trader, replay session, scenario/version, model version, and reconstruction/data version. If a run uses multiple adjustment versions, represent that relationship explicitly with a bridge; do not duplicate its measures once per version. Home/away/target team and submission/effective dates are different roles of their respective dimensions.

The fact grains above are proposals. Fix unique business keys, dimension version policies, and measure definitions before writing ETL. If probabilities are stored for multiple spread lines, use a separate run × line × side grain, with push handling and real-versus-hypothetical provenance; do not ambiguously store several lines in one run-level probability field.

Useful questions include:

- At what game stages do traders submit or withdraw adjustments?
- Which controls are used most often, and for how long do versions stay active?
- How do baseline and adjusted distributions differ for comparable runs?
- What are run latency and failure rates by model version and simulation budget?
- How well are baseline probabilities calibrated on chronological evaluation games?

Warehouse loading must be idempotent, preserve operational IDs/version references, and record load provenance and rejected rows. Raw source anomalies remain traceable; any later analytical filtering must be explicit.

Do not sum win probabilities across runs. Combine histogram counts only when bin definitions and the population being summarized are compatible. Multiple checkpoints from one game are correlated. Adjusted scenarios have no observed counterfactual labels, so their accuracy cannot be established by comparing them directly with the original final score. Monte Carlo uncertainty and model error are distinct.

## 9. Open decisions before implementation

1. Does a trader activate directly, or must a reviewer approve first?
2. Are working sessions individual, shared, or both, and what happens on replay rewind?
3. Confirm whether one active version per session/team is the first-version conflict policy.
4. Specify expiry choices and the rules for pending, replaced, withdrawn, and expired adjustments.
5. Choose fixed control columns versus parameter detail rows and freeze parameter semantics/versioning.
6. Define run/comparison grouping, retry behavior, model identity, and reproducibility metadata.
7. Define canonical game/possession references and the RDS–Atlas document ownership boundary.
8. Finalize warehouse grains, business keys, dimension history, metric definitions, and ETL recovery.

## 10. Next-session handoff

Completed in this note: capture the conceptual operational workflow and proposed simulation-specific analytical model in English. No DDL, operational application, warehouse, cloud connection, migration, or performance validation is claimed.

After the current HDFS pipeline work, settle the open business decisions, produce a small ER model and concrete constraints, then implement the minimum real workflow before deriving analytical facts. Do not manufacture operational transaction volume to satisfy a requirement.

Suggested continuation prompt:

> Read AGENTS.md and this handoff. Continue designing the normalized trader operational database and a separate warehouse tailored to simulation. Start with the approval policy, possession timing, session scope, and version lifecycle. Keep proposals distinct from confirmed decisions. Do not modify historical NBA data or create paid infrastructure.
