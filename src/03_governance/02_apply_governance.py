# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 3 / Unity Catalog governance
# MAGIC
# MAGIC Applies the production payer governance posture over the care-gap medallion:
# MAGIC least-privilege grants, a governed consumption zone carrying real UC column
# MAGIC masks and row filters, lookup-driven row-level security, and the governed
# MAGIC classification taxonomy (sensitivity / PII-entity / data-domain / tier tags).
# MAGIC
# MAGIC The raw medallion tables (bronze/silver/gold) are materialized views and
# MAGIC streaming tables owned by the Lakeflow pipeline, so UC will not let masks or
# MAGIC filters attach to them directly (`EXPECT_TABLE_NOT_VIEW`). The faithful payer
# MAGIC pattern is therefore a **governed consumption zone**: lock the medallion down
# MAGIC to engineers / the pipeline service principal / break-glass clinical staff, and
# MAGIC expose masked, row-filtered managed Delta serving tables in `governance` to the
# MAGIC business personas (care coordinators, quality analysts).
# MAGIC
# MAGIC Identities (groups + service principals) are created out of band by
# MAGIC `01_identities.py`. This notebook is idempotent and parameterized by widgets.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
# Service principals stand in for the personas. This metastore identity is a
# workspace admin, not an account admin, so UC-grantable account groups can't be
# created here; UC grants only accept account-level principals (users / service
# principals), so grants target these SPs. The mask/row-filter policy still keys on
# native is_member() over the workspace persona groups the SPs belong to, and the
# documented account-group grant model ships alongside as 02b_grants_account_groups.sql.
dbutils.widgets.text("coord_principal", "07369d4b-134b-42bb-b2aa-25c57456404d",
                     "Care-coordinator SP application_id")
dbutils.widgets.text("analyst_principal", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337",
                     "Quality-analyst SP application_id")
dbutils.widgets.text("engineer_principal", "e42fda52-f9e2-478c-b4a4-abba32a1b601",
                     "Data-engineer / pipeline SP application_id")

CATALOG = dbutils.widgets.get("catalog")
TESTER = dbutils.widgets.get("coord_principal")  # coordinator SP also seeds the RLS scope
COORD_SP = dbutils.widgets.get("coord_principal")
ANALYST_SP = dbutils.widgets.get("analyst_principal")
ENGINEER_SP = dbutils.widgets.get("engineer_principal")

# Persona workspace groups the model grants against.
G_COORD = "zrb_stars_care_coordinators"
G_ANALYST = "zrb_stars_quality_analysts"
G_ENG = "zrb_stars_data_engineers"
G_PHI = "zrb_stars_phi_authorized"
G_ADMIN = "zrb_stars_admins"

spark.sql(f"USE CATALOG {CATALOG}")


import time


def run(sql):
    # Consecutive ALTER TABLE SET MASK / SET ROW FILTER on one table race on the
    # table's metadata etag (ABORTED.UC_ETAG_MISMATCH). Retry that transient.
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


# COMMAND ----------

# MAGIC %md ## 1. Governance schema

# COMMAND ----------

run("CREATE SCHEMA IF NOT EXISTS governance "
    "COMMENT 'Governed consumption zone: masked, row-filtered serving tables plus RLS config and policy functions.'")
run("DROP FUNCTION IF EXISTS governance._probe_mask")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Row-level security map
# MAGIC Which contracts each care coordinator may see. `principal` holds the value
# MAGIC `current_user()` returns: an email for a person, the application id for a
# MAGIC service principal. Analysts, engineers, break-glass, and admins are not listed
# MAGIC here; the row filter grants them the full population by group instead.

# COMMAND ----------

run("""
CREATE TABLE IF NOT EXISTS governance.coordinator_scope (
  principal   STRING  NOT NULL COMMENT 'current_user() value: email (person) or application_id (service principal)',
  contract_id STRING  NOT NULL COMMENT 'Medicare contract the coordinator is assigned to',
  assigned_at TIMESTAMP        COMMENT 'When the assignment was granted'
)
COMMENT 'Row-level security assignment map for care coordinators (lookup-driven RLS).'
""")

# Idempotent seed: the never-privileged tester SP is assigned contract H1234 only,
# so its view of the worklist is both column-masked and row-trimmed.
run(f"DELETE FROM governance.coordinator_scope WHERE principal = '{TESTER}'")
run(f"INSERT INTO governance.coordinator_scope VALUES ('{TESTER}', 'H1234', current_timestamp())")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Policy functions (masks + row filter)
# MAGIC UC invokes these with the function owner's authority, but `is_member()` and
# MAGIC `current_user()` resolve to the querying identity, so the same table yields a
# MAGIC different result per persona. Only `zrb_stars_phi_authorized` sees unmasked PHI.

# COMMAND ----------

# member_id: a direct identifier (MBI stand-in). Coordinators must act on the real id;
# analysts get a stable SHA-256 pseudonym that still supports grouping and joins.
run(f"""
CREATE OR REPLACE FUNCTION governance.fn_mask_member_id(mid STRING)
RETURNS STRING
COMMENT 'Cleartext for coordinators + break-glass; SHA-256 pseudonym for everyone else.'
RETURN CASE
  WHEN is_member('{G_PHI}') OR is_member('{G_COORD}') OR is_member('{G_ADMIN}') THEN mid
  ELSE sha2(mid, 256)
END
""")

# birth_date: a HIPAA Safe-Harbor identifier. Generalized to the first of the birth
# year for everyone except break-glass clinical staff.
run(f"""
CREATE OR REPLACE FUNCTION governance.fn_mask_birth_date(bd DATE)
RETURNS DATE
COMMENT 'Generalized to birth year unless break-glass clinical access.'
RETURN CASE WHEN is_member('{G_PHI}') THEN bd ELSE trunc(bd, 'YEAR') END
""")

# Clinical measurements: redacted to NULL unless break-glass.
run(f"""
CREATE OR REPLACE FUNCTION governance.fn_mask_clinical(v DOUBLE)
RETURNS DOUBLE
COMMENT 'Raw clinical value redacted unless break-glass clinical access.'
RETURN CASE WHEN is_member('{G_PHI}') THEN v ELSE NULL END
""")

# Dual-eligible: sensitive socioeconomic status. Analysts keep it for equity
# stratification; coordinators and other roles do not.
run(f"""
CREATE OR REPLACE FUNCTION governance.fn_mask_dual(b BOOLEAN)
RETURNS BOOLEAN
COMMENT 'Low-income subsidy status: visible to analysts + break-glass only.'
RETURN CASE WHEN is_member('{G_PHI}') OR is_member('{G_ANALYST}') THEN b ELSE NULL END
""")

# Row filter: break-glass / admins / analysts / engineers see the whole population;
# a coordinator sees only the contracts assigned to them in coordinator_scope.
# NOTE: the parameter is p_contract_id, not contract_id. An unqualified contract_id
# inside the correlated subquery would bind to coordinator_scope's own column, making
# the predicate a tautology and defeating the filter.
run(f"""
CREATE OR REPLACE FUNCTION governance.fn_rls_contract(p_contract_id STRING)
RETURNS BOOLEAN
COMMENT 'Contract-scoped RLS: coordinators limited to assigned contracts, other roles unrestricted.'
RETURN
  is_member('{G_PHI}') OR is_member('{G_ADMIN}') OR is_member('{G_ANALYST}') OR is_member('{G_ENG}')
  OR exists (
    SELECT 1 FROM governance.coordinator_scope s
    WHERE s.principal = current_user() AND s.contract_id = p_contract_id
  )
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Consumption zone serving tables
# MAGIC Managed Delta tables the business personas read. Masks and the row filter
# MAGIC attach here (regular tables, so they survive pipeline refreshes). Rebuilt
# MAGIC idempotently from the governed medallion; counts match gold exactly.

# COMMAND ----------

# Coordinator / analyst worklist: one row per member x open-or-closed measure, with
# the member attributes needed to prioritize and act.
run("""
CREATE OR REPLACE TABLE governance.care_gaps
COMMENT 'Governed care-gap worklist. member_id/birth_date/dual_eligible masked by policy; row-filtered by contract.'
AS
SELECT
  g.member_id,
  m.contract_id,
  m.plan_id,
  g.measure_id,
  w.star_weight,
  g.measurement_year,
  g.gap_status,
  g.due_date,
  m.birth_date,
  m.age,
  m.sex,
  m.county,
  m.dual_eligible,
  m.is_diabetic,
  m.is_hypertensive
FROM gold.care_gaps g
JOIN silver.members m USING (member_id)
LEFT JOIN gold.measure_weights w USING (measure_id)
""")

run("ALTER TABLE governance.care_gaps ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.care_gaps ALTER COLUMN birth_date SET MASK governance.fn_mask_birth_date")
run("ALTER TABLE governance.care_gaps ALTER COLUMN dual_eligible SET MASK governance.fn_mask_dual")
run("ALTER TABLE governance.care_gaps SET ROW FILTER governance.fn_rls_contract ON (contract_id)")

# Clinical labs surface: raw readings for population analytics, clinically redacted
# unless break-glass.
run("""
CREATE OR REPLACE TABLE governance.member_labs
COMMENT 'Governed lab readings. result_value clinically masked; member_id masked; row-filtered by contract.'
AS
SELECT
  m.member_id,
  m.contract_id,
  CAST(l.loinc AS STRING) AS loinc,
  l.test_name,
  CAST(l.result_value AS DOUBLE) AS result_value,
  l.result_date
FROM bronze.lab_results l
JOIN silver.members m USING (member_id)
""")

run("ALTER TABLE governance.member_labs ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.member_labs ALTER COLUMN result_value SET MASK governance.fn_mask_clinical")
run("ALTER TABLE governance.member_labs SET ROW FILTER governance.fn_rls_contract ON (contract_id)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Classification tags
# MAGIC Conform to this metastore's governed tag policies: `sensitivity`
# MAGIC (pii/internal/public), the `class.<entity>` PII-entity presence tags
# MAGIC (empty value), `gov_data_domain`, `fs_tier`, and `system.certification_status`.
# MAGIC A free-form `care_gap_data_class` carries the finer semantic class.

# COMMAND ----------

# Catalog + schema domain / tier tags.
run(f"ALTER CATALOG {CATALOG} SET TAGS ('gov_data_domain' = 'clinical')")
run("ALTER SCHEMA bronze SET TAGS ('fs_tier' = 'bronze', 'gov_data_domain' = 'raw')")
run("ALTER SCHEMA silver SET TAGS ('fs_tier' = 'silver', 'gov_data_domain' = 'clinical')")
run("ALTER SCHEMA gold   SET TAGS ('fs_tier' = 'gold', 'gov_data_domain' = 'analytics')")
run("ALTER SCHEMA governance SET TAGS ('gov_data_domain' = 'analytics')")

# Column-level sensitivity + PII-entity + semantic class. Helper keeps it readable.
def tag_col(table, column, sensitivity, data_class, pii_entity=None):
    tags = [f"'sensitivity' = '{sensitivity}'", f"'care_gap_data_class' = '{data_class}'"]
    if pii_entity:
        tags.append(f"'class.{pii_entity}' = ''")
    run(f"ALTER TABLE {table} ALTER COLUMN {column} SET TAGS ({', '.join(tags)})")


# Governed consumption tables (durable: regular Delta).
tag_col("governance.care_gaps", "member_id", "pii", "direct_identifier")
tag_col("governance.care_gaps", "birth_date", "pii", "demographic", "date_of_birth")
tag_col("governance.care_gaps", "age", "pii", "demographic", "age")
tag_col("governance.care_gaps", "county", "pii", "quasi_identifier", "location")
tag_col("governance.care_gaps", "dual_eligible", "pii", "socioeconomic")
tag_col("governance.care_gaps", "gap_status", "pii", "clinical")
tag_col("governance.member_labs", "member_id", "pii", "direct_identifier")
tag_col("governance.member_labs", "result_value", "pii", "clinical")

# Source-of-truth columns on the medallion (best-effort: pipeline refreshes may
# reset tags on managed MVs, which is why the enforced surface is the Delta zone).
tag_col("silver.members", "member_id", "pii", "direct_identifier")
tag_col("silver.members", "birth_date", "pii", "demographic", "date_of_birth")
tag_col("silver.members", "dual_eligible", "pii", "socioeconomic")
tag_col("bronze.lab_results", "result_value", "pii", "clinical")

# Certify the governed serving tables.
run("ALTER TABLE governance.care_gaps SET TAGS ('system.certification_status' = 'certified')")
run("ALTER TABLE governance.member_labs SET TAGS ('system.certification_status' = 'certified')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Least-privilege grants
# MAGIC No `PUBLIC` grants. Grants target the real account-grantable principals (the
# MAGIC persona service principals); break-glass + admin are the catalog owner / current
# MAGIC user. Business personas never touch the raw medallion; they read the governed
# MAGIC consumption zone only.

# COMMAND ----------

# Everyone who works in the catalog needs USE CATALOG.
for p in (COORD_SP, ANALYST_SP, ENGINEER_SP):
    run(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{p}`")

# Raw medallion: the data-engineer / pipeline SP reads and writes. Coordinators and
# analysts get nothing here; break-glass + admin read via the owner/current-user grant.
for schema in ("bronze", "silver", "gold"):
    run(f"GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA {schema} TO `{ENGINEER_SP}`")

# Governance zone: every persona SP may enter the schema.
for p in (COORD_SP, ANALYST_SP, ENGINEER_SP):
    run(f"GRANT USE SCHEMA ON SCHEMA governance TO `{p}`")

# Worklist: coordinator + analyst (break-glass + admin read as owner).
for p in (COORD_SP, ANALYST_SP):
    run(f"GRANT SELECT ON TABLE governance.care_gaps TO `{p}`")

# Labs: analyst only (coordinators do not need raw labs; the grant model proves it
# by the coordinator SP being denied at query time).
run(f"GRANT SELECT ON TABLE governance.member_labs TO `{ANALYST_SP}`")

# coordinator_scope is RLS configuration, not consumer data: left to owner/admins only.

# COMMAND ----------

# MAGIC %md ## 7. Summary

# COMMAND ----------

print("Governance applied.")
print("Consumption zone:", CATALOG + ".governance.care_gaps / .member_labs (masked + row-filtered)")
print("Policy functions:", "fn_mask_member_id, fn_mask_birth_date, fn_mask_clinical, fn_mask_dual, fn_rls_contract")
print("Persona groups:", ", ".join([G_COORD, G_ANALYST, G_ENG, G_PHI, G_ADMIN]))
display(spark.sql("SELECT * FROM governance.coordinator_scope"))
