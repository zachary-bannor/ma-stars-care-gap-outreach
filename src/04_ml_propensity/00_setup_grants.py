#!/usr/bin/env python3
"""Layer 4 setup: the two grants the ML job needs that Layer 3 did not provide.

Layer 3 gave the engineer / pipeline service principal USE SCHEMA + SELECT +
MODIFY on the medallion, enough to read silver and write data into existing gold
tables. The ML job, running as that same service principal, additionally has to
*create* gold.gap_scores and *register* a Unity Catalog model, which are distinct
privileges. This grants exactly those, nothing broader, so the least-privilege
posture holds. Run once as an admin / catalog owner before the job:

    python3 src/04_ml_propensity/00_setup_grants.py

GRANTs are idempotent, so re-running is safe.
"""
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "3c261b5b5dfe9c21"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
# Data-engineer / pipeline service principal (medallion owner; Layer 4 run_as).
ENGINEER_SP = "e42fda52-f9e2-478c-b4a4-abba32a1b601"

w = WorkspaceClient(profile=PROFILE)


def run(sql):
    print("· " + " ".join(sql.split()))
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE, statement=sql, catalog=CATALOG, wait_timeout="50s")
    if r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if r.status.error else f"did not succeed (state={r.status.state})"
        raise RuntimeError(f"{msg}\n  SQL: {sql}")


# USE CATALOG so the SP can resolve the catalog; CREATE TABLE so it can create
# gold.gap_scores and the staged evidence tables; CREATE MODEL so it can register
# the propensity model into the gold schema.
run(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{ENGINEER_SP}`")
run(f"GRANT CREATE TABLE ON SCHEMA {CATALOG}.gold TO `{ENGINEER_SP}`")
run(f"GRANT CREATE MODEL ON SCHEMA {CATALOG}.gold TO `{ENGINEER_SP}`")
print("Layer 4 grants applied to the engineer service principal.")
