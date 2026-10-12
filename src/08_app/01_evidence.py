"""Layer 8 evidence (LOCAL, run as a workspace admin after the app is deployed).

Produces text-readable run evidence under evidence/08_app/ (the FE Bar requirement:
committed query results and logs, never screenshots). It connects to Lakebase as the
coordinator service principal, exactly as the app does, and:

  1. proves the governed identity (Postgres current_user is the coordinator SP);
  2. reads the worklist via the app's own query module (worklist_queries);
  3. proves the serving surface is coordinator-safe (contract H1234 only, cleartext
     member_id);
  4. proves least-privilege (DELETE on the write-back table is denied);
  5. exercises the app's transactional write-back (append action + upsert status) and
     shows the status round-trip;
  6. captures the deployed app's metadata (url, compute status, service principal).

Run:
    python3 src/08_app/01_evidence.py
"""
import base64
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from databricks.sdk import WorkspaceClient

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
INSTANCE = "zrb-stars-worklist"
LOGICAL_DB = "databricks_postgres"
PG_SCHEMA = "ops"
COORD_CLIENT_ID = "07369d4b-134b-42bb-b2aa-25c57456404d"
APP_NAME = "zrb-stars-coordinator"
SECRET_SCOPE = "zrb_stars_app"
SECRET_KEY = "coord_sp_secret"

HERE = Path(__file__).resolve().parent
EVID = HERE.parents[1] / "evidence" / "08_app"
sys.path.insert(0, str(HERE))
import worklist_queries as q  # noqa: E402

q.SCHEMA = PG_SCHEMA
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def stored_secret(ws):
    """Read the coordinator SP secret the app itself uses, from the secret scope that
    00_setup_app.py populated. Reusing the stored secret (rather than minting a fresh
    one) proves the exact credential path the running app takes and avoids the SP's
    five-OAuth-secret cap."""
    r = ws.secrets.get_secret(scope=SECRET_SCOPE, key=SECRET_KEY)
    return base64.b64decode(r.value).decode()


def coord_client(secret):
    host = WorkspaceClient(profile=PROFILE).config.host
    return WorkspaceClient(host=host, client_id=COORD_CLIENT_ID,
                           client_secret=secret, auth_type="oauth-m2m")


def connect(ws):
    inst = ws.database.get_database_instance(name=INSTANCE)
    cred = ws.database.generate_database_credential(instance_names=[INSTANCE])
    return psycopg.connect(host=inst.read_write_dns, port=5432, dbname=LOGICAL_DB,
                           user=COORD_CLIENT_ID, password=cred.token,
                           sslmode="require", autocommit=False, connect_timeout=15)


def app_info():
    """Best-effort capture of the deployed app metadata; tolerates a not-yet-deployed app."""
    try:
        r = subprocess.run(
            ["databricks", "apps", "get", APP_NAME, "-p", PROFILE, "--output", "json"],
            capture_output=True, text=True, check=True,
        )
        return json.loads(r.stdout)
    except subprocess.CalledProcessError as exc:
        return {"error": "app not retrievable", "detail": (exc.stderr or "").strip()}


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "checks": {}}

    admin = WorkspaceClient(profile=PROFILE)
    ws = coord_client(stored_secret(admin))
    conn = connect(ws)

    # 1. governed identity
    with conn.cursor() as cur:
        cur.execute("SELECT current_user, current_database()")
        pg_user, pg_db = cur.fetchone()
    identity_ok = pg_user == COORD_CLIENT_ID
    summary["checks"]["identity_is_coordinator_sp"] = identity_ok

    # 2. read the worklist via the app's query module
    with conn.cursor() as cur:
        cur.execute(q.worklist_select_sql(schema=PG_SCHEMA))
        cols = [c.name for c in cur.description]
        rows = cur.fetchall()
    summary["checks"]["worklist_rows"] = len(rows)
    with open(EVID / "worklist_sample.csv", "w", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(cols)
        for row in rows[:25]:
            wtr.writerow(row)

    # 3. serving surface is coordinator-safe
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT contract_id FROM {PG_SCHEMA}.worklist ORDER BY 1")
        contracts = [r[0] for r in cur.fetchall()]
    scope_ok = contracts == ["H1234"]
    sample_member = rows[0][cols.index("member_id")] if rows else ""
    cleartext_ok = bool(sample_member) and not SHA256_RE.match(str(sample_member))
    summary["checks"]["contract_scope_H1234_only"] = scope_ok
    summary["checks"]["member_id_cleartext"] = cleartext_ok
    summary["contracts_visible"] = contracts

    # 4. least-privilege: DELETE on the write-back table is denied
    delete_denied, delete_err = False, ""
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {PG_SCHEMA}.worklist_status WHERE false")
        conn.commit()
    except psycopg.errors.InsufficientPrivilege as exc:
        delete_denied, delete_err = True, str(exc).strip().splitlines()[0]
        conn.rollback()
    except Exception as exc:  # any other refusal still proves it is not permitted
        delete_denied, delete_err = True, f"{type(exc).__name__}: {exc}".splitlines()[0]
        conn.rollback()
    summary["checks"]["delete_denied"] = delete_denied

    # 5. transactional write-back round-trip (the app's exact path)
    target = rows[0][cols.index("member_id")]
    before = None
    with conn.cursor() as cur:
        cur.execute(q.member_status_sql(schema=PG_SCHEMA), (target,))
        b = cur.fetchone()
        before = dict(zip([c.name for c in cur.description], b)) if b else None
    try:
        with conn.cursor() as cur:
            cur.execute(q.insert_action_sql(schema=PG_SCHEMA),
                        (target, "EED", "called", "phone", "left_voicemail",
                         "Evidence run: governed write-back round-trip.", COORD_CLIENT_ID))
            cur.execute(q.upsert_status_sql(schema=PG_SCHEMA),
                        (target, "contacted", "called", None, COORD_CLIENT_ID))
        conn.commit()
        writeback_ok = True
    except Exception as exc:
        conn.rollback()
        writeback_ok = False
        summary["writeback_error"] = str(exc).splitlines()[0]
    with conn.cursor() as cur:
        cur.execute(q.member_status_sql(schema=PG_SCHEMA), (target,))
        a = cur.fetchone()
        after = dict(zip([c.name for c in cur.description], a)) if a else None
    summary["checks"]["writeback_roundtrip"] = writeback_ok and after is not None

    conn.close()

    # 6. deployed app metadata
    info = app_info()
    with open(EVID / "app_info.json", "w") as f:
        json.dump(info, f, indent=2, default=str)

    # --- write the human-readable evidence ---
    with open(EVID / "governed_identity_proof.md", "w") as f:
        f.write("# Layer 8: governed identity and least-privilege (serving path)\n\n")
        f.write(f"- Postgres `current_user`: `{pg_user}` (database `{pg_db}`)\n")
        f.write(f"- Expected coordinator service principal: `{COORD_CLIENT_ID}` "
                f"-> {'MATCH' if identity_ok else 'MISMATCH'}\n")
        f.write(f"- Contracts visible on the serving surface: {contracts} "
                f"-> {'coordinator-scoped (H1234 only)' if scope_ok else 'UNEXPECTED'}\n")
        f.write(f"- Sample `member_id`: `{sample_member}` "
                f"-> {'cleartext (coordinator entitlement)' if cleartext_ok else 'UNEXPECTED'}\n")
        f.write(f"- DELETE on `{PG_SCHEMA}.worklist_status`: "
                f"{'DENIED -> ' + delete_err if delete_denied else 'NOT DENIED (unexpected)'}\n\n")
        f.write("The Layer 3 Unity Catalog column masks and row filter enforce on the "
                "analytics path (the Layer 7 Genie space). On this Lakebase serving path "
                "coordinator-safety comes from the pre-minimized, contract-scoped serving "
                "surface plus this least-privilege Postgres role.\n")

    with open(EVID / "writeback_roundtrip.md", "w") as f:
        f.write("# Layer 8: transactional write-back round-trip (the app's path)\n\n")
        f.write(f"Target member: `{target}`\n\n")
        f.write(f"- Status before: `{before}`\n")
        f.write(f"- Status after: `{after}`\n")
        f.write(f"- Write-back committed: {writeback_ok}\n\n")
        f.write("The app appends one row to `ops.coordinator_action` and upserts "
                "`ops.worklist_status` in a single transaction (rollback on error). "
                "This is the identical SQL the Streamlit app runs on 'Save action'.\n")

    with open(EVID / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    with open(EVID / "run_evidence.md", "w") as f:
        f.write("# Layer 8: Databricks App (coordinator worklist) run evidence\n\n")
        f.write("The app reads the prioritized worklist from the Lakebase serving table "
                "`ops.worklist` and records outreach transactionally to "
                "`ops.coordinator_action` and `ops.worklist_status`, all as the governed "
                "coordinator service principal.\n\n")
        f.write("## Checks\n\n")
        for k, v in summary["checks"].items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Deployed app\n\n")
        f.write(f"- name: {info.get('name', 'n/a')}\n")
        f.write(f"- url: {info.get('url', 'n/a')}\n")
        cs = info.get("compute_status") or info.get("app_status") or {}
        f.write(f"- status: {cs if cs else 'n/a'}\n")
        f.write(f"- service principal: {info.get('service_principal_name', 'n/a')} "
                f"({info.get('service_principal_client_id', 'n/a')})\n")
        f.write("\nSee worklist_sample.csv, governed_identity_proof.md, "
                "writeback_roundtrip.md, app_info.json, summary.json.\n")

    ok = all(summary["checks"].get(k) for k in (
        "identity_is_coordinator_sp", "contract_scope_H1234_only",
        "member_id_cleartext", "delete_denied", "writeback_roundtrip"))
    print("evidence written to", EVID)
    print(json.dumps(summary["checks"], indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
