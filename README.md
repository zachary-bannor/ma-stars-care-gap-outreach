# Medicare Advantage Star Rating Care-Gap Outreach

Close more weighted HEDIS care gaps with the care-coordination team you already have, and move a Medicare Advantage contract across the Star rating cliff that pays.

## Why this matters, in dollars

CMS pays Medicare Advantage plans against a county benchmark. A contract rated 4.0 Stars or higher earns a 5 percentage point bonus on that benchmark. A contract below 4.0 earns nothing. Crossing from 3.5 to 4.0 Stars is the single most valuable threshold in the program.

On a synthetic 100,000-member contract, grounded in how the Quality Bonus Program actually pays:

| Input | Value |
| --- | --- |
| Benchmark revenue per member | about $1,100 PMPM ($13,200 per year) |
| Quality bonus at 4.0 Stars | 5% of benchmark |
| Bonus per member | about $55 PMPM ($660 per year) |
| Gross annual bonus opportunity, 100k members | about $66M per year |

Not all of that lands as margin. The higher benchmark also raises the rebate the plan reinvests in supplemental benefits, which is itself a retention lever. A conservative retained-plus-reinvested value of $200 to $400 per member per year still clears $20M to $40M on one contract. One contract, one Star tier, tens of millions.

The gap today is targeting. Coordinators dial through gap lists in roughly the order they arrive, so capacity gets spent on members who would have closed on their own and on members who will not respond, while persuadable members near a Star cut point go uncalled. This build ranks every open gap by how much closing it moves the Star score and how likely outreach is to close it, serves that ranked worklist to coordinators, and drafts the outreach for them. Same headcount, more weighted gaps closed, higher Star rating.

**Buyer:** VP of Stars / Quality, Medicare & Retirement. **KPIs moved:** contract Star rating, measure-level gap closure rate, weighted gaps closed per coordinator hour, voluntary disenrollment.

## The data flow, one picture

```
Synthetic raw files          Lakeflow                Gold                 Lakebase             Databricks App
(claims, rx, labs,    ->   Auto Loader + DLT   ->   care_gaps +     ->   coordinator    ->   coordinator
 roster, providers,        bronze/silver/gold       gap_scores           worklist +          worklist UI
 outreach history)                                  (ML scores)          outreach_log        (GenAI drafts)

              [ Unity Catalog governs, masks, and traces every box above ]
              [ Genie sits on Gold for the quality manager ]
              [ Unity AI Gateway governs the GenAI drafting endpoint ]
```

One connected journey, raw files to a worklist a coordinator actually works. The targeted HEDIS measures are the triple-weighted diabetes medication adherence measure (MAD, Part D weight 3) plus four clinical gaps: eye exam for diabetes (EED), glycemic status assessment (GSD), controlling high blood pressure (CBP), and colorectal screening (COL). MAD moves the Star score most per gap closed, so the ranking feels its weight.

## The six layers

| Layer | What it does | Status |
| --- | --- | --- |
| 1. Data generation | Seeded synthetic senior MA population, raw source files landed in a volume | Built |
| 2. Lakeflow pipeline | Auto Loader + DLT, bronze to gold, re-derives HEDIS gaps with data-quality expectations | Built |
| 3. Unity Catalog governance | Governed consumption zone with column masks + contract row filter, least-privilege grants, PHI classification tags, lineage, three-persona enforcement proof | Built |
| 4. ML propensity model | Gradient-boosted propensity-to-close, MLflow tracked, UC registered, batch scored | Built |
| 5. GenAI drafting | Governed Unity AI Gateway endpoint (guardrails, rate limit, usage tracking) over Claude Sonnet 5.5, drafts human-review outreach with no PHI sent to the model | Built |
| 6. Lakebase worklist | Managed Postgres serving the ranked worklist with transactional write-back; ai_decide picks the per-member lead ask | Built |
| 7. Genie space | Natural-language analytics over the gold tables for the quality manager | Planned |
| 8. Databricks App | Coordinator worklist UI, reads Lakebase, logs outreach back | Planned |

## Running it

This repo is a Databricks Asset Bundle. It deploys to a Databricks workspace with Unity Catalog and serverless compute.

```bash
# authenticate a CLI profile against your workspace
databricks auth login --host <your-workspace-url> --profile <profile>

# deploy and run layer 1 (generates the synthetic raw data)
databricks bundle deploy -t dev -p <profile>
databricks bundle run data_generation -t dev -p <profile>
```

Layer 1 creates schemas `bronze`, `silver`, `gold`, `ops` inside the target catalog, generates the synthetic population, and lands raw CSV files in the `bronze.raw_landing` volume. The catalog defaults to the workspace's pre-provisioned catalog and is a bundle variable (`catalog`), so you can point it at any catalog you own. Set the `dev_mode` job parameter to `true` for a 10,000-member run while iterating.

Layer 6 provisions and serves from Lakebase (managed Postgres). The worklist build runs as a bundle job; the instance setup, sync, and write-back proof run locally and need a Postgres client:

```bash
pip install "psycopg[binary]"
python3 src/06_lakebase_worklist/00_setup_lakebase.py        # instance, roles, write-back tables (idempotent)
databricks bundle run lakebase_worklist_job -t dev -p <profile>   # build ops.member_worklist (ai_decide lead decision)
python3 src/06_lakebase_worklist/02_sync_to_lakebase.py      # managed synced read table ops.worklist
python3 src/06_lakebase_worklist/03_coordinator_writeback.py # transactional write-back proof as the coordinator SP
python3 src/06_lakebase_worklist/04_evidence.py              # committed evidence
```

## Evidence, as text

Execution evidence lives in `evidence/`, one folder per layer, committed as text. No screenshots stand in for a run. Each notebook writes its own run evidence: row counts, prevalence checks, model metrics, sample query output. Layer 1 evidence (row counts, prevalence, intended open-gap counts, sample rows) is in `evidence/01_data_generation/`. Layer 2 evidence (the gap re-derivation reproducing Layer 1's 67,202 open gaps exactly, with all data-quality expectations passing) is in `evidence/02_lakeflow_pipeline/`. Layer 3 evidence (grant inventory, 38 classification tags, the applied mask and row-filter DDL, lineage, and a three-persona enforcement proof run under real principals) is in `evidence/03_governance/`. Layer 4 evidence (model metrics, calibration, feature importance, sample gap scores) is in `evidence/04_ml_propensity/`. Layer 5 evidence (gateway config, prompt, sample drafts across all five measures, inference log) is in `evidence/05_genai_drafting/`. Layer 6 evidence (the worklist with the materialized ai_decide lead decision plus confidence and probabilities, the members where sequencing diverges from pure EV, and the transactional write-back proof under the coordinator service principal) is in `evidence/06_lakebase_worklist/`.

## Decisions and trade-offs

**Streaming claims, batch labs.** Gap value decays with staleness, so claims and pharmacy fills land as monthly files and ingest as streaming/append tables. Labs and roster change slowly, so batch is fine. Freshness where it pays, simplicity where it does not.

**Lakebase instead of serving gold directly.** The coordinator worklist is transactional: single-row reads and outreach write-back. Pushing that onto an analytics gold table means slow lookups and no clean write path. Lakebase is the right tool and the clearest reason-to-exist in the build. The worklist is a managed synced table from the gold build; the write-back lives in native Postgres tables registered back into Unity Catalog, so operational truth reaches the governed lakehouse and Genie with no reverse ETL.

**EV ranks, ai_decide sequences.** Expected Star-weighted value ranks the worklist, and that number stays the exec-defensible one. On top of it, `ai_decide` makes a per-member judgment EV does not: which single open measure to lead the next contact with, and whether to bundle a second ask or keep the burden to one. The decision is batch-materialized into worklist columns with its confidence and per-option probabilities, and a guard snaps any out-of-set choice back to the member's top-EV gap. It sequences the ask; it never overrides the ranking.

**A propensity model instead of a rule.** "Call everyone with an open gap" wastes finite coordinator capacity. The model concentrates capacity on persuadable, high-weight members. The case is the lift chart, not an assertion.

**GenAI drafts, humans decide.** The model writes the outreach message and the plain-language reason note. The coordinator sends. No member is contacted automatically, so clinical and compliance review stay in the loop.

**Measure selection for impact.** Target the triple-weighted adherence measure plus four clinical gaps, not all 40-plus Star measures. Maximum Star movement per build hour.

**Honest model signal.** The generator injects a latent closure propensity driven by observable features (tenure, digital channel, distance to provider, dual-eligibility) and samples prior-year outcomes from it. The latent probability itself is never emitted, and the model trains on last year's outreach outcomes to score this year's open gaps. Train on the past, score the present.

## Synthetic data and attestation

All data is synthetic and generated in this repo with a fixed seed. No real UnitedHealthcare data, records, or identifiers touch the build, and there are no PHI-shaped fields. `member_id` is a generated surrogate. This is original work, not generated from a solution-builder template. The narrative and the build are the author's own.
