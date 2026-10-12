# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 7 / Governed consumption surfaces for the Genie space
# MAGIC
# MAGIC The quality-manager / VP-Stars Genie space is served to the Layer 3
# MAGIC `zrb_stars_quality_analysts` persona and must inherit that persona's governed
# MAGIC posture exactly: all contracts, `member_id` pseudonymized (SHA-256), birth year
# MAGIC only, no raw clinical values, dual-eligible visible. Genie runs every query
# MAGIC under the caller's Unity Catalog identity, so the Layer 3 masks and row filter
# MAGIC enforce themselves inside Genie with nothing new to trust.
# MAGIC
# MAGIC Today the analyst persona can read `governance.care_gaps` and
# MAGIC `governance.outreach_drafts`, but the scored EV (`gold.gap_scores`), the active
# MAGIC worklist (`ops.member_worklist`) and the reference weights (`gold.measure_weights`)
# MAGIC are engineer-owned or carry cleartext ids. Rather than grant the analyst into the
# MAGIC raw medallion / ops layer (which would break the Layer 3 posture), this notebook
# MAGIC extends the governed consumption zone with the missing projections, following the
# MAGIC exact Layer 3 pattern: a managed Delta serving table, `fn_mask_member_id` on
# MAGIC member_id, `fn_rls_contract` as the row filter, certification tags, least-privilege
# MAGIC grants.
# MAGIC
# MAGIC It also turns the governed zone into a **star schema with declared PK/FK
# MAGIC relationships** so Genie Ontology has an entity-relationship graph to reason over
# MAGIC (`member_dim` is the member entity, `measure_weights` the measure dimension; the
# MAGIC care-gap, score, worklist and draft facts reference them). Constraints are
# MAGIC informational (`NOT ENFORCED RELY`): the Lakeflow pipeline already guarantees the
# MAGIC relationships hold. Constraints are declared BEFORE masks attach, so the primary
# MAGIC key sits on the real column, not the masked projection.
# MAGIC
# MAGIC Idempotent and parameterized by widgets. Runs serverless via the
# MAGIC `genie_space_job` bundle job.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("coord_principal", "07369d4b-134b-42bb-b2aa-25c57456404d",
                     "Care-coordinator SP application_id")
dbutils.widgets.text("analyst_principal", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337",
                     "Quality-analyst SP application_id")
dbutils.widgets.text("worklist_contract", "H1234", "Contract the active worklist is scoped to")

CATALOG = dbutils.widgets.get("catalog")
COORD_SP = dbutils.widgets.get("coord_principal")
ANALYST_SP = dbutils.widgets.get("analyst_principal")
WL_CONTRACT = dbutils.widgets.get("worklist_contract")

spark.sql(f"USE CATALOG {CATALOG}")

import time


def run(sql):
    # Consecutive ALTER TABLE SET MASK / SET ROW FILTER / ADD CONSTRAINT on one table
    # race on the table's metadata etag (ABORTED.UC_ETAG_MISMATCH). Retry that transient.
    print("· " + " ".join(sql.split())[:110])
    for attempt in range(6):
        try:
            spark.sql(sql)
            return
        except Exception as e:
            msg = str(e)
            if ("UC_ETAG_MISMATCH" in msg or "has been modified" in msg) and attempt < 5:
                time.sleep(2 + attempt)
                continue
            raise


def constraint(table, name, body):
    """ADD CONSTRAINT, preferring NOT ENFORCED RELY (feeds the Genie Ontology join
    graph and the optimizer). Falls back to plain NOT ENFORCED if the runtime rejects
    RELY on this constraint type, so an older DBR still gets the declared relationship.
    Idempotent: drops any prior binding of the same name first."""
    run(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    try:
        run(f"ALTER TABLE {table} ADD CONSTRAINT {name} {body} NOT ENFORCED RELY")
    except Exception as e:
        print(f"  (RELY rejected for {name}, retrying NORELY: {str(e).splitlines()[0][:80]})")
        run(f"ALTER TABLE {table} ADD CONSTRAINT {name} {body} NOT ENFORCED")


# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Clear dependent constraints
# MAGIC Foreign keys reference the dimension primary keys, so on an idempotent re-run the
# MAGIC FKs must be dropped before the dimensions are replaced. Best-effort: a missing
# MAGIC constraint or a not-yet-existing table must not abort the rebuild.

# COMMAND ----------

_FK_CLEANUP = [
    ("governance.gap_scores", ["fk_gap_scores_member", "fk_gap_scores_measure"]),
    ("governance.worklist", ["fk_worklist_member", "fk_worklist_lead_measure"]),
    ("governance.care_gaps", ["fk_care_gaps_member", "fk_care_gaps_measure"]),
    ("governance.outreach_drafts", ["fk_drafts_member", "fk_drafts_measure"]),
]
for _tbl, _names in _FK_CLEANUP:
    for _n in _names:
        try:
            run(f"ALTER TABLE {_tbl} DROP CONSTRAINT IF EXISTS {_n}")
        except Exception as _e:
            print(f"  (skipped FK cleanup {_tbl}.{_n}: {str(_e).splitlines()[0][:80]})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Dimension: measure_weights
# MAGIC Public reference (five HEDIS measures, their Star weights and display names).
# MAGIC No PHI, so no mask and no row filter; it is the certified measure dimension the
# MAGIC facts reference and Genie resolves friendly names against.

# COMMAND ----------

run("""
CREATE OR REPLACE TABLE governance.measure_weights
COMMENT 'Measure dimension: the five HEDIS Star measures, their CMS Star weight (MAD triple-weighted) and display names. Public reference, certified.'
AS
SELECT
  CAST(measure_id AS STRING)   AS measure_id,
  CAST(measure_name AS STRING) AS measure_name,
  CAST(star_weight AS INT)     AS star_weight
FROM gold.measure_weights
""")
run("ALTER TABLE governance.measure_weights ALTER COLUMN measure_id SET NOT NULL")
constraint("governance.measure_weights", "pk_measure_weights", "PRIMARY KEY (measure_id)")
run("ALTER TABLE governance.measure_weights ALTER COLUMN measure_id SET TAGS ('care_gap_data_class' = 'reference')")
run("ALTER TABLE governance.measure_weights SET TAGS ('system.certification_status' = 'certified')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Dimension: member_dim (the member entity)
# MAGIC One governed row per member: the hub every fact references. member_id is masked
# MAGIC (SHA-256 pseudonym for the analyst), birth_date generalized to year, age capped at
# MAGIC 90, dual-eligible analyst-visible. Row-filtered by contract. Constraints declared
# MAGIC before the masks attach.

# COMMAND ----------

run("""
CREATE OR REPLACE TABLE governance.member_dim
COMMENT 'Member entity dimension: one governed row per Medicare Advantage member. member_id pseudonymized, birth_date generalized to year, age capped at 90, dual-eligible analyst-visible; row-filtered by contract.'
AS
SELECT
  m.member_id,
  m.contract_id,
  m.plan_id,
  m.birth_date,
  m.age,
  m.sex,
  m.county,
  m.dual_eligible,
  m.is_diabetic,
  m.is_hypertensive,
  CASE WHEN m.digital_channel_on_file THEN 'digital' ELSE 'mail_phone' END AS preferred_channel,
  CASE
    WHEN m.tenure_months IS NULL THEN 'established'
    WHEN m.tenure_months < 12 THEN 'new'
    WHEN m.tenure_months < 48 THEN 'established'
    ELSE 'longtime'
  END AS tenure_band
FROM silver.members m
""")
run("ALTER TABLE governance.member_dim ALTER COLUMN member_id SET NOT NULL")
constraint("governance.member_dim", "pk_member_dim", "PRIMARY KEY (member_id)")
run("ALTER TABLE governance.member_dim ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.member_dim ALTER COLUMN birth_date SET MASK governance.fn_mask_birth_date")
run("ALTER TABLE governance.member_dim ALTER COLUMN age SET MASK governance.fn_mask_age")
run("ALTER TABLE governance.member_dim ALTER COLUMN dual_eligible SET MASK governance.fn_mask_dual")
run("ALTER TABLE governance.member_dim SET ROW FILTER governance.fn_rls_contract ON (contract_id)")
run("ALTER TABLE governance.member_dim ALTER COLUMN member_id SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'direct_identifier')")
run("ALTER TABLE governance.member_dim ALTER COLUMN birth_date SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'demographic', 'class.date_of_birth' = '')")
run("ALTER TABLE governance.member_dim ALTER COLUMN dual_eligible SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'socioeconomic')")
run("ALTER TABLE governance.member_dim SET TAGS ('system.certification_status' = 'certified')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Fact: gap_scores (scored open gaps + expected Star-weighted value)
# MAGIC Governed projection of the engineer-owned `gold.gap_scores`. One row per member x
# MAGIC open measure, carrying the calibrated closure propensity and the expected
# MAGIC Star-weighted value (EV = propensity x star_weight), the exec-ranked dollar proxy.
# MAGIC measure_name denormalized for readable NL. member_id masked, row-filtered.

# COMMAND ----------

run("""
CREATE OR REPLACE TABLE governance.gap_scores
COMMENT 'Scored open care gaps: per member x open HEDIS measure, the calibrated closure propensity and expected Star-weighted value (EV = propensity x star_weight), the exec-ranked retrievable-value proxy. member_id pseudonymized; row-filtered by contract. Certified.'
AS
SELECT
  s.member_id,
  s.contract_id,
  s.measure_id,
  w.measure_name,
  s.measurement_year,
  s.propensity,
  s.star_weight,
  s.expected_weighted_value
FROM gold.gap_scores s
LEFT JOIN gold.measure_weights w USING (measure_id)
""")
run("ALTER TABLE governance.gap_scores ALTER COLUMN member_id SET NOT NULL")
run("ALTER TABLE governance.gap_scores ALTER COLUMN measure_id SET NOT NULL")
run("ALTER TABLE governance.gap_scores ALTER COLUMN measurement_year SET NOT NULL")
constraint("governance.gap_scores", "pk_gap_scores", "PRIMARY KEY (member_id, measure_id, measurement_year)")
run("ALTER TABLE governance.gap_scores ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.gap_scores SET ROW FILTER governance.fn_rls_contract ON (contract_id)")
run("ALTER TABLE governance.gap_scores ALTER COLUMN member_id SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'direct_identifier')")
run("ALTER TABLE governance.gap_scores ALTER COLUMN expected_weighted_value SET TAGS ('care_gap_data_class' = 'derived_metric')")
run("ALTER TABLE governance.gap_scores SET TAGS ('system.certification_status' = 'certified')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Fact: worklist (the active prioritized operational queue)
# MAGIC Governed projection of the Lakebase worklist source `ops.member_worklist`
# MAGIC (member-grain, top-500 by member_ev on the active contract, with the ai_decide
# MAGIC lead-outreach decision). `led_below_top_ev` flags the members where ai_decide led
# MAGIC with a lower-EV ask than the member's single highest-EV gap: the member-level
# MAGIC sequencing judgment the pure EV ranking does not make. member_id masked, row-filtered.

# COMMAND ----------

run(f"""
CREATE OR REPLACE TABLE governance.worklist
COMMENT 'Active prioritized coordinator worklist (top-500 members by member_ev on the active contract) with the ai_decide lead-outreach decision. member_ev is the sum of a member open-gap expected Star-weighted values. led_below_top_ev marks members ai_decide led with a lower-EV ask than their top gap. member_id pseudonymized; row-filtered by contract. Certified.'
AS
-- led_below_top_ev compares the ai_decide lead gap's value against the member's
-- single highest-value gap. Both EVs are read full-precision from gold.gap_scores
-- (the lead gap via a join on the chosen lead_measure, the top via MAX). Comparing
-- the worklist's stored lead_ev instead would be wrong: it is rounded, so it reads
-- below a full-precision MAX for the SAME gap and floods the flag with false ties.
WITH member_gaps AS (
  SELECT member_id, measure_id, expected_weighted_value AS ev
  FROM gold.gap_scores
  WHERE contract_id = '{WL_CONTRACT}'
),
member_top AS (
  SELECT member_id, MAX(ev) AS member_top_ev
  FROM member_gaps
  GROUP BY member_id
)
SELECT
  w.worklist_rank,
  w.member_id,
  w.contract_id,
  w.member_ev,
  w.open_gap_count,
  w.lead_measure,
  w.lead_measure_name,
  w.lead_ev,
  w.lead_propensity,
  w.lead_confidence,
  (lead_g.ev < t.member_top_ev) AS led_below_top_ev,
  w.bundle_decision,
  w.bundle_measure,
  w.bundle_measure_name,
  w.preferred_channel,
  w.tenure_band,
  w.requires_human_review
FROM ops.member_worklist w
LEFT JOIN member_gaps lead_g
  ON lead_g.member_id = w.member_id AND lead_g.measure_id = w.lead_measure
LEFT JOIN member_top t USING (member_id)
""")
run("ALTER TABLE governance.worklist ALTER COLUMN member_id SET NOT NULL")
constraint("governance.worklist", "pk_worklist", "PRIMARY KEY (member_id)")
run("ALTER TABLE governance.worklist ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.worklist SET ROW FILTER governance.fn_rls_contract ON (contract_id)")
run("ALTER TABLE governance.worklist ALTER COLUMN member_id SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'direct_identifier')")
run("ALTER TABLE governance.worklist ALTER COLUMN member_ev SET TAGS ('care_gap_data_class' = 'derived_metric')")
run("ALTER TABLE governance.worklist SET TAGS ('system.certification_status' = 'certified')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Foreign keys (the entity-relationship graph)
# MAGIC All facts reference the member entity and the measure dimension. Informational
# MAGIC (`NOT ENFORCED RELY`): the pipeline guarantees them, and they give Genie Ontology
# MAGIC the certified join paths. Added after every dimension primary key exists.

# COMMAND ----------

constraint("governance.gap_scores", "fk_gap_scores_member",
           "FOREIGN KEY (member_id) REFERENCES governance.member_dim(member_id)")
constraint("governance.gap_scores", "fk_gap_scores_measure",
           "FOREIGN KEY (measure_id) REFERENCES governance.measure_weights(measure_id)")
constraint("governance.worklist", "fk_worklist_member",
           "FOREIGN KEY (member_id) REFERENCES governance.member_dim(member_id)")
constraint("governance.worklist", "fk_worklist_lead_measure",
           "FOREIGN KEY (lead_measure) REFERENCES governance.measure_weights(measure_id)")

# Extend the graph onto the Layer 3 / Layer 5 governed facts the space also reads.
# Best-effort: these tables are owned by earlier layers and a re-run of those layers
# will drop the FK (and this layer re-adds it); a transient must not abort the grants.
for _tbl, _name, _body in [
    ("governance.care_gaps", "fk_care_gaps_member",
     "FOREIGN KEY (member_id) REFERENCES governance.member_dim(member_id)"),
    ("governance.care_gaps", "fk_care_gaps_measure",
     "FOREIGN KEY (measure_id) REFERENCES governance.measure_weights(measure_id)"),
    ("governance.outreach_drafts", "fk_drafts_member",
     "FOREIGN KEY (member_id) REFERENCES governance.member_dim(member_id)"),
    ("governance.outreach_drafts", "fk_drafts_measure",
     "FOREIGN KEY (measure_id) REFERENCES governance.measure_weights(measure_id)"),
]:
    try:
        constraint(_tbl, _name, _body)
    except Exception as _e:
        print(f"  (skipped cross-layer FK {_tbl}.{_name}: {str(_e).splitlines()[0][:80]})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Least-privilege grants
# MAGIC The Genie space serves the quality-analyst persona. Grant that SP SELECT on the
# MAGIC new governed surfaces (it already holds governance.care_gaps + outreach_drafts
# MAGIC from Layer 3 / Layer 5). The coordinator SP gets the measure dimension only; the
# MAGIC operational worklist is the coordinator app's surface in Layer 8, granted there.
# MAGIC Break-glass + admin read as owner / current user.

# COMMAND ----------

for _tbl in ("governance.member_dim", "governance.gap_scores",
             "governance.worklist", "governance.measure_weights"):
    run(f"GRANT SELECT ON TABLE {_tbl} TO `{ANALYST_SP}`")

run(f"GRANT SELECT ON TABLE governance.measure_weights TO `{COORD_SP}`")

# COMMAND ----------

# MAGIC %md ## 7. Summary

# COMMAND ----------

print("Governed Genie surfaces built in", CATALOG + ".governance:")
for _tbl in ("member_dim", "measure_weights", "gap_scores", "worklist"):
    n = spark.sql(f"SELECT COUNT(*) c FROM governance.{_tbl}").collect()[0]["c"]
    print(f"  governance.{_tbl}: {n} rows")
print("Worklist contract scope:", WL_CONTRACT)
display(spark.sql(f"""
  SELECT constraint_type, COUNT(*) AS n
  FROM {CATALOG}.information_schema.table_constraints
  WHERE table_schema = 'governance'
  GROUP BY constraint_type ORDER BY constraint_type
"""))
