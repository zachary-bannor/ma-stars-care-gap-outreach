#!/usr/bin/env python3
"""Layer 3 / Enforcement proof. Runs the SAME queries against the governed
consumption zone under three real identities and writes the differing result sets
to evidence/03_governance/. Nothing is simulated: each identity is a real principal
whose group membership drives the UC mask / row-filter engine.

  break-glass  = the current user (member of zrb_stars_phi_authorized) -> cleartext, all rows
  coordinator  = zrb_stars_governance_tester SP (member of zrb_stars_care_coordinators)
  analyst      = zrb_stars_analyst_sp SP        (member of zrb_stars_quality_analysts)

The two service-principal identities authenticate with their own OAuth M2M secrets
(minted out of band, read from /tmp/*_creds.json, never committed). Run locally:

    python3 src/03_governance/04_prove_enforcement.py
"""
import csv
import json
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "3c261b5b5dfe9c21"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "03_governance")
os.makedirs(EVID, exist_ok=True)

# Identities.
clients = {"breakglass": WorkspaceClient(profile=PROFILE)}
for persona, path in (("coordinator", "/tmp/tester_creds.json"),
                      ("analyst", "/tmp/analyst_creds.json")):
    c = json.load(open(path))
    clients[persona] = WorkspaceClient(host=c["host"], client_id=c["client_id"],
                                       client_secret=c["client_secret"])

# Queries each identity runs identically.
Q_BY_CONTRACT = ("SELECT contract_id, count(*) AS gaps "
                 f"FROM {CATALOG}.governance.care_gaps GROUP BY contract_id ORDER BY contract_id")
Q_SAMPLE = ("SELECT member_id, contract_id, measure_id, gap_status, birth_date, age, dual_eligible "
            f"FROM {CATALOG}.governance.care_gaps "
            "WHERE measure_id='EED' ORDER BY age, gap_status LIMIT 5")
Q_LABS = ("SELECT member_id, loinc, result_value "
          f"FROM {CATALOG}.governance.member_labs ORDER BY loinc LIMIT 5")


def run(client, sql):
    """Return (cols, rows) or ('ERROR', [[message]])."""
    try:
        r = client.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE, statement=sql, wait_timeout="50s")
        if r.status.state != StatementState.SUCCEEDED:
            return "ERROR", [[r.status.error.message]]
        cols = [c.name for c in r.manifest.schema.columns]
        rows = r.result.data_array if (r.result and r.result.data_array) else []
        return cols, rows
    except Exception as e:
        return "ERROR", [[str(e).splitlines()[0]]]


def fmt(cols, rows):
    if cols == "ERROR":
        return "DENIED / ERROR: " + rows[0][0]
    out = ["    " + " | ".join(cols)]
    for row in rows:
        out.append("    " + " | ".join("NULL" if v is None else str(v) for v in row))
    return "\n".join(out)


def write_csv(persona, label, cols, rows):
    path = os.path.join(EVID, f"enforcement_{persona}_{label}.csv")
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        if cols == "ERROR":
            wr.writerow(["result"]); wr.writerow(["DENIED: " + rows[0][0]])
        else:
            wr.writerow(cols)
            wr.writerows([["NULL" if v is None else v for v in row] for row in rows])


summary = ["# Layer 3 enforcement proof",
           "",
           "The same three queries, run under three real principals against the governed "
           "consumption zone. Access decisions come entirely from each principal's workspace "
           "group membership through the UC column-mask and row-filter engine.",
           ""]

for persona in ("breakglass", "coordinator", "analyst"):
    c = clients[persona]
    who = run(c, "SELECT current_user()")[1][0][0]
    summary.append(f"## {persona}  (`{who}`)\n")

    for label, sql, desc in (
        ("by_contract", Q_BY_CONTRACT, "Row filter: contracts visible"),
        ("sample", Q_SAMPLE, "Column masks: member_id / birth_date / dual_eligible"),
        ("labs", Q_LABS, "Clinical mask + table grant"),
    ):
        cols, rows = run(c, sql)
        write_csv(persona, label, cols, rows)
        summary.append(f"**{desc}**\n```\n{fmt(cols, rows)}\n```\n")

with open(os.path.join(EVID, "enforcement_summary.md"), "w") as f:
    f.write("\n".join(summary))
print("wrote enforcement_summary.md and per-persona CSVs")
print("\n".join(summary))
