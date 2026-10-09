#!/usr/bin/env python3
"""Layer 6 / Lakebase worklist: provision the managed Postgres (Lakebase) surface.

Runs locally as the workspace admin (same local-admin pattern as Layer 3's
01_identities.py, Layer 4's 00_setup_grants.py and Layer 5's 00_setup_gateway.py):

    pip install "psycopg[binary]"
    python3 src/06_lakebase_worklist/00_setup_lakebase.py

Stands up everything the worklist needs, idempotently:

  1. A Lakebase database instance `zrb-stars-worklist` (smallest capacity).
     This is the operational serving surface: single-row reads of the ranked
     worklist and single-row outreach write-backs are transactional, which the
     analytics gold tables serve poorly. That is this layer's reason to exist.
  2. Persona Postgres roles for the care-coordinator and quality-analyst service
     principals (Databricks identity -> Postgres role), mirroring the Layer 3 UC
     persona grants onto the operational surface.
  3. Two NATIVE Postgres write-back tables (not synced; synced tables are
     read-only replicas): `ops.worklist_status` (current status per work item,
     upserted) and `ops.coordinator_action` (append-only outreach log). The
     synced read table `ops.worklist` is created in 02_sync_to_lakebase.py.
  4. Registration of those two native tables into the pre-provisioned Unity
     Catalog (`create_database_table`) so the coordinator write-back is readable
     by the governed lakehouse, Genie (Layer 7) and audit with no reverse ETL.
  5. Least-privilege grants: the coordinator role writes the two write-back
     tables; the analyst role is read-only; the engineer / admin owns.

FORCED ADAPTATION (documented, same workspace-admin-not-account-admin limit as
Layers 1/3/4/5): Lakebase's own dedicated UC "database catalog" needs CREATE
CATALOG on the metastore, which this identity lacks. So, exactly like every prior
layer, we use the pre-provisioned catalog `zrb_fe_bar_uhc_stars_catalog`: the
synced table and the registered write-back tables live in its `ops` schema. The
UC schema name must match the Postgres schema name, so the Postgres schema is
also `ops`. PHI never reaches Postgres because the worklist projection is
column-minimized to coordinator-entitled fields (see worklist_sql.py).
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import database as db

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WORKSPACE_URL = "https://fevm-zrb-fe-bar-uhc-stars.cloud.databricks.com"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"

INSTANCE = "zrb-stars-worklist"
CAPACITY = "CU_1"                 # smallest Lakebase SKU
LOGICAL_DB = "databricks_postgres"  # the instance's default logical database
PG_SCHEMA = "ops"                 # must match the UC schema the tables register into

# Persona service principals (same identities proven under Layer 3 enforcement).
COORD_SP = "07369d4b-134b-42bb-b2aa-25c57456404d"    # zrb_stars_governance_tester
ANALYST_SP = "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337"  # zrb_stars_analyst_sp

WRITEBACK_TABLES = ["worklist_status", "coordinator_action"]

w = WorkspaceClient(profile=PROFILE)


def step(msg):
    print(f"\n=== {msg} ===")


# --- 1. Database instance ----------------------------------------------------
step("1. Lakebase database instance")
try:
    inst = w.database.get_database_instance(name=INSTANCE)
    print(f"· instance {INSTANCE} already exists (state={inst.state})")
except Exception:
    print(f"· creating instance {INSTANCE} (capacity {CAPACITY}) ...")
    w.database.create_database_instance(
        database_instance=db.DatabaseInstance(name=INSTANCE, capacity=CAPACITY))

deadline = time.time() + 1800
while True:
    inst = w.database.get_database_instance(name=INSTANCE)
    if inst.state == db.DatabaseInstanceState.AVAILABLE:
        break
    if inst.state in (db.DatabaseInstanceState.DELETING,):
        sys.exit(f"instance entered terminal state {inst.state}")
    if time.time() > deadline:
        sys.exit("timed out waiting for instance to become AVAILABLE")
    print(f"  ... state={inst.state}, waiting")
    time.sleep(20)
print(f"· instance AVAILABLE  rw_dns={inst.read_write_dns}  pg={inst.pg_version}")

# --- 2. Persona Postgres roles (Databricks identity -> PG role) --------------
step("2. Persona Postgres roles")
for name, kind in [(COORD_SP, "coordinator"), (ANALYST_SP, "analyst")]:
    try:
        w.database.create_database_instance_role(
            instance_name=INSTANCE,
            database_instance_role=db.DatabaseInstanceRole(
                name=name,
                identity_type=db.DatabaseInstanceRoleIdentityType.SERVICE_PRINCIPAL))
        print(f"· created PG role for {kind} SP {name}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"· PG role for {kind} SP {name} already exists")
        else:
            print(f"! role create for {kind} returned: {e}")

# --- 3. Native write-back tables (Postgres) ----------------------------------
step("3. Write-back tables (Postgres)")
try:
    import psycopg
except ImportError:
    sys.exit('psycopg not installed. Run:  pip install "psycopg[binary]"')

me = w.current_user.me().user_name
cred = w.database.generate_database_credential(instance_names=[INSTANCE])
conn = psycopg.connect(
    host=inst.read_write_dns, port=5432, dbname=LOGICAL_DB,
    user=me, password=cred.token, sslmode="require", autocommit=True)
print(f"· connected to {LOGICAL_DB} as {me}")

with conn.cursor() as cur:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.worklist_status (
            member_id       text PRIMARY KEY,
            status          text NOT NULL DEFAULT 'new',
            last_action     text,
            next_action_due timestamptz,
            updated_by      text,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )""")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.coordinator_action (
            action_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            member_id   text NOT NULL,
            measure     text,
            action      text NOT NULL,
            channel     text,
            outcome     text,
            notes       text,
            acted_by    text NOT NULL,
            acted_at    timestamptz NOT NULL DEFAULT now()
        )""")
    print("· write-back tables ready (ops.worklist_status, ops.coordinator_action)")

    # Grant to the persona PG roles (discover exact role names the mapping made).
    cur.execute("SELECT rolname FROM pg_roles")
    roles = {r[0] for r in cur.fetchall()}
    coord_role = next((r for r in roles if COORD_SP in r), COORD_SP)
    analyst_role = next((r for r in roles if ANALYST_SP in r), ANALYST_SP)
    print(f"· coordinator role -> {coord_role}")
    print(f"· analyst role     -> {analyst_role}")

    for role in (coord_role, analyst_role):
        cur.execute(f'GRANT USAGE ON SCHEMA {PG_SCHEMA} TO "{role}"')
    # Coordinator: write the operational log + status.
    cur.execute(f'GRANT SELECT, INSERT, UPDATE ON {PG_SCHEMA}.worklist_status TO "{coord_role}"')
    cur.execute(f'GRANT SELECT, INSERT ON {PG_SCHEMA}.coordinator_action TO "{coord_role}"')
    cur.execute(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA {PG_SCHEMA} TO "{coord_role}"')
    # Analyst: read-only on operational state.
    cur.execute(f'GRANT SELECT ON {PG_SCHEMA}.worklist_status TO "{analyst_role}"')
    cur.execute(f'GRANT SELECT ON {PG_SCHEMA}.coordinator_action TO "{analyst_role}"')
    print("· least-privilege grants applied (coordinator read+write, analyst read-only)")

conn.close()

# --- 4. Register the native write-back tables into Unity Catalog -------------
step("4. Register write-back tables in Unity Catalog")
for t in WRITEBACK_TABLES:
    uc_name = f"{CATALOG}.{PG_SCHEMA}.{t}"
    try:
        w.database.create_database_table(table=db.DatabaseTable(
            name=uc_name, database_instance_name=INSTANCE,
            logical_database_name=LOGICAL_DB))
        print(f"· registered {uc_name}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"· {uc_name} already registered")
        else:
            print(f"! register {uc_name} returned: {e}")

step("done")
print(f"instance={INSTANCE}  catalog={CATALOG}  schema={PG_SCHEMA}  db={LOGICAL_DB}")
print(f"rw_dns={inst.read_write_dns}")
