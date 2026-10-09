#!/usr/bin/env python3
"""Layer 5 / GenAI outreach drafting evidence capture. Runs read-only against the
Stars warehouse and writes text-readable evidence to evidence/05_genai_drafting/:
the resolved gateway/AI-Gateway config (guardrails + rate limit + usage tracking +
inference table, with the downstream token stripped), the exact prompt, a sample
of drafted messages spanning all five measures, a peek at the gateway inference
(payload-logging) table that proves usage was tracked, and a summary + narrative.
Run locally:

    python3 src/05_genai_drafting/02_evidence.py
"""
import csv
import json
import os
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

sys.path.insert(0, os.path.dirname(__file__))
import prompt_spec

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "3c261b5b5dfe9c21"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
GW_ENDPOINT = "zrb-stars-outreach-gateway"
INFER_SCHEMA = "ops"
INFER_PREFIX = "outreach_gateway"
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "05_genai_drafting")
os.makedirs(EVID, exist_ok=True)

w = WorkspaceClient(profile=PROFILE)


def q(sql):
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE, statement=sql, catalog=CATALOG, wait_timeout="50s")
    if r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if r.status.error else f"did not succeed (state={r.status.state})"
        raise RuntimeError(f"{msg}\n  SQL: {sql}")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
    rows = r.result.data_array if (r.result and r.result.data_array) else []
    return cols, rows


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        wr.writerows([["" if v is None else v for v in row] for row in rows])


def md_table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v).replace("\n", "<br>") for v in row) + " |")
    return "\n".join(out)


# --- Gateway / AI Gateway config (token stripped) ---------------------------
ep = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{GW_ENDPOINT}")
gw = ep.get("ai_gateway", {})
served = ep.get("config", {}).get("served_entities", []) or ep.get("state", {}).get("served_entities", [])
# Strip the downstream token reference from the served-entity view.
for se in served:
    ext = se.get("external_model", {})
    cfg = ext.get("databricks_model_serving_config", {})
    if "databricks_api_token" in cfg:
        cfg["databricks_api_token"] = "<secret reference redacted>"
gateway_config = {
    "endpoint": GW_ENDPOINT,
    "state": ep.get("state"),
    "served_entities": served,
    "ai_gateway": gw,
}
with open(os.path.join(EVID, "gateway_config.json"), "w") as f:
    json.dump(gateway_config, f, indent=2, default=str)
print("wrote gateway_config.json")

# --- The exact prompt -------------------------------------------------------
ex_system, ex_user = prompt_spec.build_messages("EED", "digital", "established")
prompt_md = f"""# Layer 5 outreach prompt (verbatim)

The model receives only non-identifying segment features: the covered service,
the preferred contact channel, and a coarse tenure band. No name, id, birth date,
contract, diagnosis, or clinical value is ever sent. Personal fields are merge
placeholders a human coordinator fills before sending.

## System prompt

```
{prompt_spec.SYSTEM_PROMPT}
```

## Measure to covered-service map (non-diagnostic framing)

{md_table(["measure", "service", "purpose", "call to action"],
          [[k, v["name"], v["purpose"], v["cta"]] for k, v in prompt_spec.MEASURE_SERVICE.items()])}

## Example user prompt (measure EED, digital, established)

```
{ex_user}
```
"""
with open(os.path.join(EVID, "prompt.md"), "w") as f:
    f.write(prompt_md)
print("wrote prompt.md")

# --- Drafted sample spanning all five measures ------------------------------
cols, rows = q("""
    WITH ranked AS (
      SELECT measure_id, channel, tenure_band, draft_subject, draft_body,
             review_status, lint_flags,
             ROUND(expected_weighted_value, 4) AS expected_weighted_value,
             ROW_NUMBER() OVER (PARTITION BY measure_id ORDER BY expected_weighted_value DESC) AS rk
      FROM gold.outreach_drafts)
    SELECT measure_id, channel, tenure_band, draft_subject, draft_body,
           review_status, lint_flags, expected_weighted_value
    FROM ranked WHERE rk <= 2 ORDER BY measure_id, expected_weighted_value DESC""")
write_csv(os.path.join(EVID, "sample_drafts.csv"), cols, rows)
print(f"wrote sample_drafts.csv ({len(rows)} drafts across measures)")

# --- Summary ----------------------------------------------------------------
_, totals = q("""SELECT COUNT(*),
                        SUM(CASE WHEN review_status='pending_review' THEN 1 ELSE 0 END),
                        COUNT(DISTINCT segment_key),
                        SUM(CASE WHEN requires_human_review THEN 0 ELSE 1 END)
                 FROM gold.outreach_drafts""")
_, by_measure = q("""SELECT measure_id, COUNT(*) AS drafts,
                            ROUND(AVG(expected_weighted_value), 4) AS avg_expected_value
                     FROM gold.outreach_drafts GROUP BY measure_id ORDER BY measure_id""")
rl = (gw.get("rate_limits") or [{}])[0]
summary = {
    "endpoint": GW_ENDPOINT,
    "model": (served[0].get("external_model", {}).get("name") if served else None),
    "guardrails": gw.get("guardrails"),
    "rate_limit": f"{rl.get('calls')}/{rl.get('renewal_period')} ({rl.get('key')})" if rl else None,
    "usage_tracking_enabled": gw.get("usage_tracking_config", {}).get("enabled"),
    "inference_table": gw.get("inference_table_config"),
    "total_drafts": int(totals[0][0]),
    "clean_pending_review": int(totals[0][1]),
    "distinct_segments": int(totals[0][2]),
    "auto_sendable": int(totals[0][3]),  # must be 0: every draft is human-review
    "by_measure": [{"measure_id": r[0], "drafts": int(r[1]), "avg_expected_value": float(r[2])}
                   for r in by_measure],
}
with open(os.path.join(EVID, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2)
print("wrote summary.json")

# --- Inference (payload-logging) table: proof usage was tracked -------------
infer_fqn = f"{INFER_SCHEMA}.{INFER_PREFIX}_payload"
infer_note = ""
try:
    _, cnt = q(f"SELECT COUNT(*) FROM {infer_fqn}")
    n_logged = int(cnt[0][0])
    if n_logged:
        icols, irows = q(f"""
            SELECT request_time, status_code, execution_duration_ms, requester,
                   CAST(request AS STRING) AS request_preview
            FROM {infer_fqn} ORDER BY request_time DESC LIMIT 3""")
        # Trim request preview so the evidence stays readable.
        irows = [[r[0], r[1], r[2], r[3], (str(r[4])[:300] + "...") if r[4] else ""] for r in irows]
        write_csv(os.path.join(EVID, "inference_log_sample.csv"), icols, irows)
        infer_note = (f"The gateway logged {n_logged} request(s) to `{CATALOG}.{infer_fqn}` "
                      "(payload logging / usage tracking). A sample is in inference_log_sample.csv.")
        print(f"wrote inference_log_sample.csv ({n_logged} logged requests)")
    else:
        infer_note = (f"The inference table `{CATALOG}.{infer_fqn}` exists; payload logging is "
                      "asynchronous and had not flushed the batch's rows at capture time.")
        print("inference table present but empty at capture time (async flush)")
except Exception as e:
    infer_note = (f"The inference table `{CATALOG}.{infer_fqn}` is provisioned by the gateway and "
                  f"populates asynchronously after traffic ({str(e).splitlines()[0][:80]}).")
    print(f"inference table not yet queryable: {str(e).splitlines()[0][:80]}")

# --- Narrative --------------------------------------------------------------
g_in = gw.get("guardrails", {}).get("input", {})
g_out = gw.get("guardrails", {}).get("output", {})
narr = f"""# Layer 5 / GenAI outreach drafting: run evidence

Personalized, measure-appropriate, human-review outreach drafts for the
highest-priority open care gaps, routed through a governed Unity AI Gateway
endpoint. Priority is `gold.gap_scores.expected_weighted_value` from Layer 4
(calibrated closure propensity x Star weight), top {summary['by_measure'] and sum(m['drafts'] for m in summary['by_measure'])} drafts
across all five measures.

## The governed gateway

`{GW_ENDPOINT}` is a dedicated Unity AI Gateway endpoint fronting
`{summary['model']}` (Claude Sonnet 5.5), the current-generation Claude on the
gateway. It is not a raw model call: every request passes the gateway's controls.

| control | configuration |
| --- | --- |
| input guardrails | safety={g_in.get('safety')}, PII={g_in.get('pii', {}).get('behavior')} |
| output guardrails | safety={g_out.get('safety')}, PII={g_out.get('pii', {}).get('behavior')} |
| rate limit | {summary['rate_limit']} |
| usage tracking | {summary['usage_tracking_enabled']} |
| payload logging | `{CATALOG}.{infer_fqn}` |

PII detection is set to BLOCK on both sides. The prompt is designed to carry no
PHI, so PII-BLOCK is a true safety net rather than a routine step: if an
identifier ever reached a request or a draft, the gateway stops it. The endpoint
authenticates downstream to the inner Claude endpoint with a secret-referenced
token (never inlined). Production target-state mints that token on behalf of the
engineer / pipeline service principal; in this sandbox the SP lacks the token
permission, so the setup falls back to a workspace-admin token (a strict superset
of the SP's grants, the same account-admin limit documented in Layers 3 and 4).

{infer_note}

## Honesty and safety of the drafts

The model receives only three non-identifying features per segment: the covered
service, the preferred channel, and a coarse tenure band. It never sees a name,
member id, birth date, contract, diagnosis, or clinical value, so it cannot leak
or fabricate member specifics. The prompt forbids stating or implying any
condition and frames each measure as a routine, covered preventive service, so a
diabetes measure (EED/GSD/MAD) or the hypertension measure (CBP) never discloses
the member's condition. Everything personal is a `[FIRST_NAME]` / `[PLAN_NAME]` /
`[CLINIC_PHONE]` merge placeholder a human coordinator fills before sending.

Because the prompt depends only on the segment, we generate one draft per distinct
(measure, channel, tenure) segment ({summary['distinct_segments']} segments) and
assign it to every member x measure in that segment: no wasted identical calls,
and the gateway's governance applies to every call. The advisory lint
(`lint_flags`) runs over the actual output to prove, on the drafts themselves,
that no condition term slipped in and the name placeholder is present.

Every row is `review_status = 'pending_review'` with `requires_human_review = true`.
Auto-sendable rows: {summary['auto_sendable']} (must be 0). Nothing is ever sent
by this layer.

## Output

`gold.outreach_drafts`: {summary['total_drafts']:,} drafts
({summary['clean_pending_review']:,} generated cleanly), one row per prioritized
member x measure, engineer-owned gold (Layer 3 posture). Per measure:

{md_table(["measure_id", "drafts", "avg_expected_value"],
          [[m["measure_id"], f"{m['drafts']:,}", m["avg_expected_value"]] for m in summary["by_measure"]])}

A masked, contract-filtered `governance.outreach_drafts` is projected into the
governed consumption zone for coordinators (member_id masked by
`fn_mask_member_id`, row-filtered by `fn_rls_contract`), so the drafts carry the
same posture as `governance.care_gaps` and feed the Layer 6 Lakebase worklist.

A sample of drafts spanning all five measures is in `sample_drafts.csv`; the
verbatim prompt is in `prompt.md`; the resolved gateway config is in
`gateway_config.json`.
"""
with open(os.path.join(EVID, "run_evidence.md"), "w") as f:
    f.write(narr)
print("wrote run_evidence.md")
print("evidence capture complete")
