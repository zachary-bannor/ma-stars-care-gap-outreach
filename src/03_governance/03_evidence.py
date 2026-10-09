#!/usr/bin/env python3
"""Layer 3 / Governance evidence capture. Runs read-only against the Stars warehouse
as the current (break-glass) identity and writes text-readable evidence to
evidence/03_governance/: the grant inventory, classification tag inventory, the
applied mask/row-filter policy definitions, and UC lineage. Run locally:

    python3 src/03_governance/03_evidence.py
"""
import csv
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "3c261b5b5dfe9c21"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "03_governance")
os.makedirs(EVID, exist_ok=True)

w = WorkspaceClient(profile=PROFILE)


def q(sql):
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE, statement=sql, catalog=CATALOG, wait_timeout="50s")
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.error.message}\n  SQL: {sql}")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
    rows = r.result.data_array if (r.result and r.result.data_array) else []
    return cols, rows


def md_table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        wr.writerows([["" if v is None else v for v in row] for row in rows])


# --- Grant inventory --------------------------------------------------------
# Grants target SP application_ids; map them to the persona they represent so the
# inventory reads cleanly.
PERSONA = {
    "07369d4b-134b-42bb-b2aa-25c57456404d": "care-coordinator SP (zrb_stars_governance_tester)",
    "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337": "quality-analyst SP (zrb_stars_analyst_sp)",
    "e42fda52-f9e2-478c-b4a4-abba32a1b601": "data-engineer SP (zrb_stars_pipeline_sp)",
    "zachary.bannor@databricks.com": "admin + break-glass (current user)",
    "aec5be3d-de3c-404c-8e60-feed0f265fd3": "deployer SP (catalog owner)",
}
grant_objs = [
    ("CATALOG", CATALOG),
    ("SCHEMA", f"{CATALOG}.bronze"),
    ("SCHEMA", f"{CATALOG}.silver"),
    ("SCHEMA", f"{CATALOG}.gold"),
    ("SCHEMA", f"{CATALOG}.governance"),
    ("TABLE", f"{CATALOG}.governance.care_gaps"),
    ("TABLE", f"{CATALOG}.governance.member_labs"),
    ("TABLE", f"{CATALOG}.governance.coordinator_scope"),
]
sections = ["# Layer 3 grant inventory",
            "",
            "Least-privilege grant model. Business personas (coordinator, analyst) hold no "
            "privileges on the raw medallion; they read the governed consumption zone only. No "
            "`PUBLIC` grants; no `ALL_PRIVILEGES` outside the owner/admin. Grants target the "
            "persona service principals because this sandbox identity cannot create "
            "UC-grantable account groups (see 02b_grants_account_groups.sql for the production "
            "group model). Principal ids are annotated with the persona they represent.",
            ""]
for otype, okey in grant_objs:
    cols, rows = q(f"SHOW GRANTS ON {otype} {okey}")
    cols = cols + ["Persona"]
    # Keep only grants made AT this object (drop rows inherited from the catalog).
    kept = []
    for r in rows:
        if r[3] == okey:  # grant made at this object, not inherited from the catalog
            kept.append(list(r) + [PERSONA.get(str(r[0]), "")])
    sections.append(f"## {otype} `{okey}`\n\n{md_table(cols, kept)}\n")
with open(os.path.join(EVID, "grants.md"), "w") as f:
    f.write("\n".join(sections))
print("wrote grants.md")

# --- Classification tag inventory ------------------------------------------
tag_rows_all, tag_cols = [], ["level", "object", "column", "tag_key", "tag_value"]
cols, rows = q(f"SELECT catalog_name, tag_name, tag_value FROM {CATALOG}.information_schema.catalog_tags")
tag_rows_all += [["catalog", r[0], "", r[1], r[2]] for r in rows]
cols, rows = q(f"SELECT schema_name, tag_name, tag_value FROM {CATALOG}.information_schema.schema_tags ORDER BY schema_name")
tag_rows_all += [["schema", r[0], "", r[1], r[2]] for r in rows]
cols, rows = q(f"SELECT schema_name||'.'||table_name, tag_name, tag_value FROM {CATALOG}.information_schema.table_tags ORDER BY 1")
tag_rows_all += [["table", r[0], "", r[1], r[2]] for r in rows]
cols, rows = q(f"SELECT schema_name||'.'||table_name, column_name, tag_name, tag_value FROM {CATALOG}.information_schema.column_tags ORDER BY 1,2")
tag_rows_all += [["column", r[0], r[1], r[2], r[3]] for r in rows]
write_csv(os.path.join(EVID, "tag_inventory.csv"), tag_cols, tag_rows_all)
print(f"wrote tag_inventory.csv ({len(tag_rows_all)} tags)")

# --- Applied mask / row-filter policy definitions --------------------------
policy = ["# Applied column masks, row filters, and policy functions", ""]
for tbl in ("care_gaps", "member_labs"):
    _, rows = q(f"SHOW CREATE TABLE {CATALOG}.governance.{tbl}")
    policy.append(f"## governance.{tbl}\n\n```sql\n{rows[0][0]}\n```\n")
_, rows = q(f"""SELECT routine_name, routine_definition
               FROM {CATALOG}.information_schema.routines
               WHERE specific_schema='governance' ORDER BY routine_name""")
policy.append("## Policy functions\n")
for name, defn in rows:
    policy.append(f"### governance.{name}\n\n```sql\n{defn}\n```\n")
with open(os.path.join(EVID, "applied_policies.md"), "w") as f:
    f.write("\n".join(policy))
print("wrote applied_policies.md")

# --- Lineage ---------------------------------------------------------------
try:
    cols, rows = q(f"""
        SELECT source_table_full_name, target_table_full_name, event_time
        FROM system.access.table_lineage
        WHERE target_table_catalog = '{CATALOG}' AND source_table_full_name IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY source_table_full_name, target_table_full_name ORDER BY event_time DESC)=1
        ORDER BY target_table_full_name, source_table_full_name""")
    write_csv(os.path.join(EVID, "lineage.csv"), cols, rows)
    print(f"wrote lineage.csv ({len(rows)} edges)")
except Exception as e:
    with open(os.path.join(EVID, "lineage.csv"), "w") as f:
        f.write(f"# lineage system table not yet populated at capture time: {e}\n")
    print("lineage not yet available (system table lag) - noted")

print("evidence capture complete")
