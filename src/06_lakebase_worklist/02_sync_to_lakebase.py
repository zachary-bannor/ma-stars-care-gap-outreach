#!/usr/bin/env python3
"""Layer 6 / Lakebase worklist: sync the built worklist into Lakebase, read-side.

Runs locally as the workspace admin:

    python3 src/06_lakebase_worklist/02_sync_to_lakebase.py

Creates a MANAGED synced table `ops.worklist` in the pre-provisioned catalog from
the Delta source `ops.member_worklist` (01). A synced table is Databricks-managed
reverse ETL: a read-optimized Postgres replica kept in step with the Delta source,
which is exactly the point-latency read surface a coordinator app needs. It is a
Unity Catalog object, so it stays governed and is queryable from the lakehouse and
Genie (Layer 7) as well as directly from Postgres.

SNAPSHOT policy: a one-time full copy at creation. The worklist is rebuilt per
cycle, so re-running this script refreshes the replica. TRIGGERED and CONTINUOUS
are the production refresh options (a one-line change to the scheduling policy).

The write-back tables (ops.worklist_status, ops.coordinator_action) were created
and registered in 00; this script grants the coordinator and analyst Postgres
roles SELECT on the synced read table, completing the least-privilege posture.
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import database as db

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
INSTANCE = "zrb-stars-worklist"
LOGICAL_DB = "databricks_postgres"
PG_SCHEMA = "ops"

SOURCE = f"{CATALOG}.ops.member_worklist"
SYNCED = f"{CATALOG}.ops.worklist"

COORD_SP = "07369d4b-134b-42bb-b2aa-25c57456404d"
ANALYST_SP = "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337"

ONLINE = {
    db.SyncedTableState.SYNCED_TABLE_ONLINE,
    db.SyncedTableState.SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE,
    db.SyncedTableState.SYNCED_TABLE_ONLINE_CONTINUOUS_UPDATE,
    db.SyncedTableState.SYNCED_TABLE_ONLINE_TRIGGERED_UPDATE,
}
FAILED = {
    db.SyncedTableState.SYNCED_TABLE_OFFLINE_FAILED,
    db.SyncedTableState.SYNCED_TABLE_ONLINE_PIPELINE_FAILED,
}

w = WorkspaceClient(profile=PROFILE)


def step(msg):
    print(f"\n=== {msg} ===")


# --- 1. Create the synced table ----------------------------------------------
step("1. Synced read table ops.worklist")
try:
    existing = w.database.get_synced_database_table(name=SYNCED)
    print(f"· {SYNCED} already exists (state="
          f"{existing.data_synchronization_status.detailed_state if existing.data_synchronization_status else '?'})")
except Exception:
    print(f"· creating synced table {SYNCED} from {SOURCE} (SNAPSHOT) ...")
    w.database.create_synced_database_table(synced_table=db.SyncedDatabaseTable(
        name=SYNCED,
        database_instance_name=INSTANCE,
        logical_database_name=LOGICAL_DB,
        spec=db.SyncedTableSpec(
            source_table_full_name=SOURCE,
            primary_key_columns=["member_id"],
            scheduling_policy=db.SyncedTableSchedulingPolicy.SNAPSHOT,
            create_database_objects_if_missing=True,
            new_pipeline_spec=db.NewPipelineSpec(
                storage_catalog=CATALOG, storage_schema=PG_SCHEMA))))

# --- 2. Wait for the initial sync to land ------------------------------------
step("2. Wait for sync online")
deadline = time.time() + 1200
while True:
    t = w.database.get_synced_database_table(name=SYNCED)
    state = t.data_synchronization_status.detailed_state if t.data_synchronization_status else None
    msg = t.data_synchronization_status.message if t.data_synchronization_status else ""
    if state in ONLINE:
        print(f"· online: {state}")
        break
    if state in FAILED:
        sys.exit(f"sync failed: {state} {msg}")
    if time.time() > deadline:
        sys.exit(f"timed out waiting for sync (last state={state})")
    print(f"  ... {state} {msg}")
    time.sleep(15)

# --- 3. Grant the synced read table to the persona roles ---------------------
step("3. Grant synced table to persona roles (Postgres)")
import psycopg

inst = w.database.get_database_instance(name=INSTANCE)
me = w.current_user.me().user_name
cred = w.database.generate_database_credential(instance_names=[INSTANCE])
conn = psycopg.connect(host=inst.read_write_dns, port=5432, dbname=LOGICAL_DB,
                       user=me, password=cred.token, sslmode="require", autocommit=True)
with conn.cursor() as cur:
    cur.execute("SELECT rolname FROM pg_roles")
    roles = {r[0] for r in cur.fetchall()}
    coord_role = next((r for r in roles if COORD_SP in r), COORD_SP)
    analyst_role = next((r for r in roles if ANALYST_SP in r), ANALYST_SP)
    for role in (coord_role, analyst_role):
        cur.execute(f'GRANT SELECT ON {PG_SCHEMA}.worklist TO "{role}"')
    print(f"· granted SELECT on {PG_SCHEMA}.worklist to coordinator + analyst roles")

    # --- 4. Verify both read paths -------------------------------------------
    step("4. Verify read paths")
    cur.execute(f"SELECT count(*) FROM {PG_SCHEMA}.worklist")
    print(f"· Postgres row count: {cur.fetchone()[0]}")
    t0 = time.time()
    cur.execute(f"SELECT member_id, worklist_rank, lead_measure, lead_confidence "
                f"FROM {PG_SCHEMA}.worklist ORDER BY worklist_rank LIMIT 1")
    top = cur.fetchone()
    cur.execute(f"SELECT member_id, lead_measure, bundle_decision FROM {PG_SCHEMA}.worklist "
                f"WHERE member_id = %s", (top[0],))
    pt = cur.fetchone()
    print(f"· Postgres point-lookup member_id={pt[0]} lead={pt[1]} bundle={pt[2]} "
          f"({(time.time()-t0)*1000:.0f} ms incl. 2 queries)")
conn.close()

uc = w.statement_execution.execute_statement(
    warehouse_id="3c261b5b5dfe9c21", catalog=CATALOG, wait_timeout="30s",
    statement=f"SELECT COUNT(*) AS n FROM {SYNCED}")
print(f"· Unity Catalog read of {SYNCED}: {uc.result.data_array[0][0]} rows (governed)")

step("done")
print(f"synced={SYNCED}  source={SOURCE}  instance={INSTANCE}")
