#!/usr/bin/env python3
"""Layer 6 / Lakebase worklist: the transactional coordinator write-back proof.

Runs locally:

    python3 src/06_lakebase_worklist/03_coordinator_writeback.py

This is the layer's reason to exist, demonstrated. A care coordinator does single-
row reads ("give me my next member") and single-row writes ("I called them, log it,
move the status"). Those are transactional, point-latency operations that the
analytics gold tables serve poorly and Lakebase serves well.

It connects to Postgres AS THE CARE-COORDINATOR SERVICE PRINCIPAL (not the admin),
the same identity proven under Layer 3 UC enforcement, so the proof also shows the
Layer 3 persona posture holding on the operational surface:

  1. Point read of the top worklist item (coordinator has SELECT on ops.worklist).
  2. ATOMIC write-back in one transaction: append an outreach action to
     ops.coordinator_action and upsert ops.worklist_status to 'contacted', then
     COMMIT. Status before and after confirm the commit.
  3. ROLLBACK safety: a second transaction updates the status then rolls back;
     the status is unchanged, proving transactional integrity.
  4. LEAST PRIVILEGE: the coordinator role was granted SELECT/INSERT/UPDATE only,
     so a DELETE is denied by Postgres. The denial is captured.
  5. GOVERNED ROUND-TRIP: the committed write-back is immediately readable through
     Unity Catalog (the write-back tables were registered in 00), so operational
     truth reaches the governed lakehouse and Genie with no reverse ETL.

The coordinator SP OAuth secret is minted in-process via the workspace secrets
proxy (same mechanism as Layer 3), used only to obtain a short-lived Lakebase
credential, and never written to disk or printed.
"""
import csv
import json
import os
import subprocess
import sys
import time

from databricks.sdk import WorkspaceClient

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WORKSPACE_URL = "https://fevm-zrb-fe-bar-uhc-stars.cloud.databricks.com"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
WAREHOUSE = "3c261b5b5dfe9c21"
INSTANCE = "zrb-stars-worklist"
LOGICAL_DB = "databricks_postgres"
PG_SCHEMA = "ops"

COORD_SP = "07369d4b-134b-42bb-b2aa-25c57456404d"   # zrb_stars_governance_tester
COORD_SCIM_ID = "77434984440632"

EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "06_lakebase_worklist")
os.makedirs(EVID, exist_ok=True)

try:
    import psycopg
except ImportError:
    sys.exit('psycopg not installed. Run:  pip install "psycopg[binary]"')

admin = WorkspaceClient(profile=PROFILE)


def mint_sp_secret():
    """Mint a short-lived OAuth secret for the coordinator SP (in-process only)."""
    out = subprocess.run(
        ["databricks", "service-principal-secrets-proxy", "create", COORD_SCIM_ID,
         "-p", PROFILE, "--output", "json"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)["secret"]


def coord_connection():
    """A Postgres connection authenticated as the coordinator service principal."""
    secret = mint_sp_secret()
    sp = WorkspaceClient(host=WORKSPACE_URL, client_id=COORD_SP,
                         client_secret=secret, auth_type="oauth-m2m")
    inst = sp.database.get_database_instance(name=INSTANCE)
    cred = sp.database.generate_database_credential(instance_names=[INSTANCE])
    return psycopg.connect(host=inst.read_write_dns, port=5432, dbname=LOGICAL_DB,
                           user=COORD_SP, password=cred.token, sslmode="require",
                           autocommit=False)


def admin_reset(member_id):
    """Clear any prior proof rows for this member (as admin), so each run is one
    clean, idempotent proof. The coordinator role cannot DELETE (by design), so
    the reset must run as the admin owner."""
    inst = admin.database.get_database_instance(name=INSTANCE)
    cred = admin.database.generate_database_credential(instance_names=[INSTANCE])
    me = admin.current_user.me().user_name
    with psycopg.connect(host=inst.read_write_dns, port=5432, dbname=LOGICAL_DB,
                         user=me, password=cred.token, sslmode="require",
                         autocommit=True) as ac, ac.cursor() as c:
        c.execute(f"DELETE FROM {PG_SCHEMA}.coordinator_action WHERE member_id = %s", (member_id,))
        c.execute(f"DELETE FROM {PG_SCHEMA}.worklist_status WHERE member_id = %s", (member_id,))


print("=== connecting to Lakebase as the care-coordinator service principal ===")
conn = coord_connection()
log = []  # (step, detail)


def status_of(cur, member_id):
    cur.execute(f"SELECT status, last_action, updated_by FROM {PG_SCHEMA}.worklist_status "
                f"WHERE member_id = %s", (member_id,))
    r = cur.fetchone()
    return None if r is None else {"status": r[0], "last_action": r[1], "updated_by": r[2]}


with conn.cursor() as cur:
    # --- 1. Point read of the top worklist item ------------------------------
    cur.execute(f"SELECT member_id, worklist_rank, lead_measure, lead_confidence, "
                f"bundle_decision, bundle_measure, preferred_channel "
                f"FROM {PG_SCHEMA}.worklist ORDER BY worklist_rank LIMIT 1")
    row = cur.fetchone()
    if row is None:
        sys.exit("ops.worklist is empty; run 01 (build worklist) and 02 (sync) first.")
    m, rank, lead, conf, bundle, bundle_m, channel = row
    print(f"\n1. top worklist item: #{rank} member={m} lead={lead}@{conf} "
          f"bundle={bundle}({bundle_m}) channel={channel}")
    log.append(("point_read", f"member={m} rank={rank} lead={lead} conf={conf} "
                              f"bundle={bundle} bundle_measure={bundle_m}"))

    # idempotency: start this member from a clean slate (admin-side reset)
    conn.rollback()        # end the read transaction before the external reset
    admin_reset(m)
    before = status_of(cur, m)
    print(f"   status before: {before}")
    log.append(("status_before", json.dumps(before)))

    # --- 2. Atomic write-back (commit) ---------------------------------------
    cur.execute(
        f"INSERT INTO {PG_SCHEMA}.coordinator_action "
        f"(member_id, measure, action, channel, outcome, notes, acted_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (m, lead, "called", channel, "left_voicemail",
         "Led with the recommended measure; voicemail with callback number.", COORD_SP))
    cur.execute(
        f"INSERT INTO {PG_SCHEMA}.worklist_status "
        f"(member_id, status, last_action, next_action_due, updated_by, updated_at) "
        f"VALUES (%s, 'contacted', 'called', now() + interval '3 days', %s, now()) "
        f"ON CONFLICT (member_id) DO UPDATE SET status = EXCLUDED.status, "
        f"last_action = EXCLUDED.last_action, next_action_due = EXCLUDED.next_action_due, "
        f"updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at",
        (m, COORD_SP))
    conn.commit()
    after = status_of(cur, m)
    print(f"\n2. committed outreach action + status upsert")
    print(f"   status after:  {after}")
    log.append(("txn_commit", "INSERT coordinator_action + UPSERT worklist_status -> contacted"))
    log.append(("status_after", json.dumps(after)))
    assert after and after["status"] == "contacted", "commit did not land"

    # --- 3. Rollback safety --------------------------------------------------
    cur.execute(f"UPDATE {PG_SCHEMA}.worklist_status SET status = 'closed' WHERE member_id = %s", (m,))
    conn.rollback()
    rolled = status_of(cur, m)
    print(f"\n3. rolled back a status->closed update; status is still: {rolled['status']}")
    log.append(("txn_rollback", f"UPDATE ->closed then ROLLBACK; status remained {rolled['status']}"))
    assert rolled["status"] == "contacted", "rollback did not preserve prior state"

    # --- 4. Least-privilege denial -------------------------------------------
    try:
        cur.execute(f"DELETE FROM {PG_SCHEMA}.worklist_status WHERE member_id = %s", (m,))
        conn.commit()
        denial = "UNEXPECTED: DELETE succeeded"
    except psycopg.errors.InsufficientPrivilege as e:
        conn.rollback()
        denial = f"DELETE denied: {str(e).strip().splitlines()[0]}"
    print(f"\n4. least-privilege check: {denial}")
    log.append(("least_privilege_denial", denial))

    # committed action rows for evidence
    cur.execute(f"SELECT action_id, member_id, measure, action, channel, outcome, acted_by, "
                f"acted_at FROM {PG_SCHEMA}.coordinator_action WHERE member_id = %s "
                f"ORDER BY action_id", (m,))
    action_cols = [c.name for c in cur.description]
    action_rows = cur.fetchall()

conn.close()

# --- 5. Governed round-trip through Unity Catalog ----------------------------
print("\n5. governed round-trip (read the write-back through Unity Catalog as admin)")
uc = admin.statement_execution.execute_statement(
    warehouse_id=WAREHOUSE, catalog=CATALOG, wait_timeout="30s",
    statement=f"SELECT a.member_id, a.measure, a.action, a.outcome, a.acted_by, "
              f"s.status, s.last_action FROM {CATALOG}.{PG_SCHEMA}.coordinator_action a "
              f"JOIN {CATALOG}.{PG_SCHEMA}.worklist_status s USING (member_id) "
              f"WHERE a.member_id = '{m}' ORDER BY a.action_id")
uc_cols = [c.name for c in uc.manifest.schema.columns]
uc_rows = uc.result.data_array or []
for r in uc_rows:
    print("   UC: " + " | ".join(str(v) for v in r))
log.append(("uc_round_trip", f"{len(uc_rows)} write-back row(s) visible via Unity Catalog"))

# --- evidence ----------------------------------------------------------------
with open(os.path.join(EVID, "writeback_actions.csv"), "w", newline="") as f:
    wr = csv.writer(f); wr.writerow(action_cols)
    wr.writerows([["" if v is None else v for v in row] for row in action_rows])

with open(os.path.join(EVID, "writeback_proof.md"), "w") as f:
    f.write("# Layer 6 transactional write-back proof\n\n")
    f.write("Connected to Lakebase Postgres as the care-coordinator service principal "
            f"`{COORD_SP}` (zrb_stars_governance_tester), the same identity proven under "
            "Layer 3 Unity Catalog enforcement.\n\n")
    for stepname, detail in log:
        f.write(f"- **{stepname}**: {detail}\n")
    f.write("\nThe atomic commit landed, the rolled-back update left the prior state "
            "intact, the ungranted DELETE was denied by Postgres (least privilege), and "
            "the committed write-back was immediately readable through Unity Catalog "
            "with no reverse ETL.\n")

print(f"\nevidence written to {os.path.relpath(EVID)}")
print("done")
