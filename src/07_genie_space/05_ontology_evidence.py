#!/usr/bin/env python3
"""Layer 7 / Ontology evidence. Dumps the Unity Catalog metadata that constitutes
the Genie Ontology for this space: the declared PK/FK relationship graph, the
certified metric view, the certification tags (the OntoRank authority signal), and
the table/column comments Genie reads for semantics. All text-readable, committed to
evidence/07_genie_space/.

Runs locally as the admin via the OAuth profile:

    python3 src/07_genie_space/05_ontology_evidence.py
"""
import csv
import os
import time
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "c6360590bf1c28d6"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "07_genie_space")
os.makedirs(EVID, exist_ok=True)
w = WorkspaceClient(profile=PROFILE)


def run(sql):
    r = w.statement_execution.execute_statement(warehouse_id=WAREHOUSE, statement=sql, wait_timeout="50s")
    sid = r.statement_id
    for _ in range(80):
        if r.status.state in (StatementState.SUCCEEDED, StatementState.FAILED,
                              StatementState.CANCELED, StatementState.CLOSED):
            break
        time.sleep(3)
        r = w.statement_execution.get_statement(sid)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error.message if r.status.error else str(r.status.state))
    cols = [c.name for c in r.manifest.schema.columns]
    rows = r.result.data_array if (r.result and r.result.data_array) else []
    return cols, rows


def dump_csv(name, cols, rows):
    with open(os.path.join(EVID, name), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        wr.writerows([["NULL" if v is None else v for v in row] for row in rows])


def md_table(cols, rows, limit=200):
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


QUERIES = {
    "constraints": (
        "Declared relationship graph (PK/FK). These are what Genie Ontology reads as "
        "certified entity keys and join paths.",
        f"""SELECT table_name, constraint_name, constraint_type
            FROM {CATALOG}.information_schema.table_constraints
            WHERE table_schema = 'governance'
            ORDER BY table_name, constraint_type DESC, constraint_name"""),
    "foreign_keys": (
        "Foreign-key column mappings (child column -> referenced dimension).",
        f"""SELECT kcu.table_name AS child_table, kcu.column_name AS child_column,
                   ccu.table_name AS parent_table, ccu.column_name AS parent_column,
                   kcu.constraint_name
            FROM {CATALOG}.information_schema.key_column_usage kcu
            JOIN {CATALOG}.information_schema.table_constraints tc
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.constraint_schema = tc.constraint_schema
             AND tc.constraint_type = 'FOREIGN KEY'
            JOIN {CATALOG}.information_schema.constraint_column_usage ccu
              ON kcu.constraint_name = ccu.constraint_name
             AND kcu.constraint_schema = ccu.constraint_schema
            WHERE kcu.table_schema = 'governance'
            ORDER BY child_table, kcu.constraint_name"""),
    "metric_views": (
        "Certified metric view(s): the authoritative measure definitions.",
        f"""SELECT table_schema, table_name, table_type
            FROM {CATALOG}.information_schema.tables
            WHERE table_type = 'METRIC_VIEW'
            ORDER BY table_schema, table_name"""),
    "certification_tags": (
        "Certification tags = the OntoRank authority signal. Governed surfaces + metric "
        "view are certified; the scratch trap is deprecated.",
        f"""SELECT catalog_name, schema_name, table_name, tag_name, tag_value
            FROM {CATALOG}.information_schema.table_tags
            WHERE tag_name = 'system.certification_status'
            ORDER BY tag_value, schema_name, table_name"""),
    "table_comments": (
        "Table semantics Genie reads.",
        f"""SELECT table_schema, table_name, comment
            FROM {CATALOG}.information_schema.tables
            WHERE table_schema IN ('governance', 'analytics_sandbox')
              AND comment IS NOT NULL
            ORDER BY table_schema, table_name"""),
}


def main():
    sections = ["# Layer 7 ontology evidence",
                "",
                "The Genie Ontology for this space is not a toggle; it is the Unity Catalog "
                "metadata Genie consumes automatically: a declared entity-relationship graph "
                "(PK/FK), a certified metric view, certification tags that drive OntoRank "
                "authority, and curated comments. This is that metadata, read back from "
                "information_schema.",
                ""]
    for name, (desc, sql) in QUERIES.items():
        try:
            cols, rows = run(sql)
            dump_csv(f"ontology_{name}.csv", cols, rows)
            sections.append(f"## {name.replace('_', ' ')}\n\n{desc}\n\n{md_table(cols, rows)}\n")
            print(f"{name}: {len(rows)} rows")
        except Exception as e:
            sections.append(f"## {name.replace('_', ' ')}\n\n{desc}\n\n_query error: {str(e).splitlines()[0]}_\n")
            print(f"{name}: ERROR {str(e).splitlines()[0][:120]}")
    with open(os.path.join(EVID, "ontology_evidence.md"), "w") as f:
        f.write("\n".join(sections))
    print("wrote ontology_evidence.md")


if __name__ == "__main__":
    main()
