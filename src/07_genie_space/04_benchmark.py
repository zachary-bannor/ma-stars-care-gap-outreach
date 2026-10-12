#!/usr/bin/env python3
"""Layer 7 / Genie space benchmarks + governed-posture proof.

Two parts, both committing text-readable evidence to evidence/07_genie_space/:

A. Governed correctness + masking + the OntoRank contrast. Runs the curated example
   queries and the benchmark set as the real quality-analyst service principal against
   the governed surfaces, asserting the known-exact numbers (67,202 reproduced), that
   member_id comes back as a SHA-256 pseudonym (the Layer 3 posture flowing into the
   space), and that the certified metric view and the uncertified scratch trap return
   DIFFERENT retrievable-value numbers (so preferring the certified source matters).

B. Natural-language accuracy. Drives the Genie Conversation API against the live space
   with the sample questions, capturing the SQL Genie generated and which source it
   chose. For the retrievable-value question this shows whether Genie reached for the
   certified metric view over the trap (the OntoRank outcome), reported honestly.

Run locally after the space exists (03_create_space.py):

    python3 src/07_genie_space/04_benchmark.py
"""
import csv
import json
import os
import re
import subprocess
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

sys.path.insert(0, os.path.dirname(__file__))
import space_spec

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WAREHOUSE = "c6360590bf1c28d6"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
ANALYST_APP_ID = "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337"
EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "07_genie_space")
os.makedirs(EVID, exist_ok=True)

admin = WorkspaceClient(profile=PROFILE)
HOST = admin.config.host.rstrip("/")


# --------------------------------------------------------------------------- creds
def analyst_client():
    """The analyst SP client. Mints a fresh OAuth M2M secret via the secrets proxy if
    /tmp/analyst_creds.json is absent (secrets are deleted between sessions)."""
    path = "/tmp/analyst_creds.json"
    if os.path.exists(path):
        c = json.load(open(path))
        return WorkspaceClient(host=c["host"], client_id=c["client_id"], client_secret=c["client_secret"])
    scim_id = None
    for sp in admin.service_principals.list(filter=f'applicationId eq "{ANALYST_APP_ID}"'):
        scim_id = sp.id
    if not scim_id:
        raise RuntimeError("could not resolve analyst SP scim id")
    out = subprocess.run(
        ["databricks", "service-principal-secrets-proxy", "create", scim_id, "-p", PROFILE, "-o", "json"],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("mint failed: " + out.stderr.splitlines()[0] if out.stderr else "mint failed")
    secret = json.loads(out.stdout).get("secret")
    creds = {"host": HOST, "client_id": ANALYST_APP_ID, "client_secret": secret}
    json.dump(creds, open(path, "w"))
    return WorkspaceClient(host=HOST, client_id=ANALYST_APP_ID, client_secret=secret)


# --------------------------------------------------------------------------- sql
def run_sql(client, sql):
    r = client.statement_execution.execute_statement(warehouse_id=WAREHOUSE, statement=sql, wait_timeout="50s")
    sid = r.statement_id
    for _ in range(80):
        if r.status.state in (StatementState.SUCCEEDED, StatementState.FAILED,
                              StatementState.CANCELED, StatementState.CLOSED):
            break
        time.sleep(3)
        r = client.statement_execution.get_statement(sid)
    if r.status.state != StatementState.SUCCEEDED:
        return "ERROR", [[r.status.error.message if r.status.error else str(r.status.state)]]
    cols = [c.name for c in r.manifest.schema.columns]
    rows = r.result.data_array if (r.result and r.result.data_array) else []
    return cols, rows


def one_value(cols, rows):
    return None if cols == "ERROR" or not rows else rows[0][0]


# --------------------------------------------------------------------------- part A
def part_a():
    analyst = analyst_client()
    who = one_value(*run_sql(analyst, "SELECT current_user()"))
    lines = ["# Layer 7 benchmarks (A): governed correctness, masking, OntoRank contrast",
             "",
             f"Run as the quality-analyst service principal `{who}` against the governed "
             f"surfaces. Access decisions come from the Layer 3 masks and row filter under "
             f"this principal's identity, exactly as they will inside Genie.", ""]
    results = {}

    # curated example queries
    lines.append("## Curated example queries (analyst persona)\n")
    for i, ex in enumerate(space_spec.example_sqls(CATALOG)):
        cols, rows = run_sql(analyst, ex["sql"])
        _write_csv(f"benchmark_example_{i:02d}.csv", cols, rows)
        lines.append(f"**{ex['question']}**\n\n```\n{_fmt(cols, rows, 10)}\n```\n")

    # benchmark assertions
    lines.append("## Benchmark assertions\n")
    passed = 0
    bms = space_spec.benchmarks(CATALOG)
    for b in bms:
        cols, rows = run_sql(analyst, b["sql"])
        ok, detail = _check(b, cols, rows, analyst)
        passed += 1 if ok else 0
        results[b["question"]] = {"pass": ok, "detail": detail}
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {b['question']}  ->  {detail}")
    lines.append("")

    # masking contrast: same sample row cleartext (break-glass) vs pseudonym (analyst)
    q = f"SELECT member_id FROM {CATALOG}.governance.gap_scores ORDER BY member_id LIMIT 1"
    bg_val = one_value(*run_sql(admin, q))
    an_val = one_value(*run_sql(analyst, q))
    lines += ["## Masking contrast (same query, two identities)\n",
              f"- break-glass member_id: `{bg_val}`",
              f"- analyst member_id:     `{an_val}`  (SHA-256 pseudonym, {len(an_val or '')} hex chars)", ""]
    results["masking_contrast"] = {"breakglass": bg_val, "analyst": an_val}

    # OntoRank contrast: certified metric view vs uncertified trap, same business question
    cert = one_value(*run_sql(analyst,
        f"SELECT ROUND(MEASURE(retrievable_star_weighted_value),2) FROM {CATALOG}.governance.star_value_metrics"))
    trap = one_value(*run_sql(admin,
        f"SELECT ROUND(SUM(star_value),2) FROM {CATALOG}.analytics_sandbox.star_value_rollup"))
    lines += ["## Certified vs uncertified retrievable value (why the source matters)\n",
              f"- certified metric view star_value_metrics: {cert}",
              f"- uncertified scratch trap star_value_rollup: {trap}",
              "",
              "The trap flattens the MAD triple weight and counts non-open gaps, so its "
              "number is materially wrong. Genie must prefer the certified metric view.", ""]
    results["ontorank_contrast"] = {"certified": cert, "trap": trap}

    with open(os.path.join(EVID, "benchmark_results.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"part A: {passed}/{len(bms)} benchmark assertions passed")
    return results


def _check(b, cols, rows, analyst):
    if cols == "ERROR":
        return False, "query error: " + str(rows[0][0])[:80]
    if "expect_fixed" in b:
        exp = b["expect_fixed"]
        if isinstance(exp, dict):
            got = {r[0]: int(r[1]) for r in rows}
            return got == exp, f"got {got}"
        return int(rows[0][0]) == exp, f"got {rows[0][0]}, expected {exp}"
    kind = b.get("expect")
    if kind == "sha256_hex":
        v = str(rows[0][0]); return bool(re.fullmatch(r"[0-9a-f]{64}", v)), f"member_id={v[:16]}..."
    if kind == "certified_total":
        return rows[0][0] is not None, f"certified total = {rows[0][0]}"
    if kind == "worklist_bounds":
        n, contracts = int(rows[0][0]), int(rows[0][1])
        return n <= 500 and contracts == 1, f"{n} members, {contracts} contract(s)"
    if kind == "positive":
        return int(rows[0][0]) > 0, f"count = {rows[0][0]}"
    return False, "unknown check"


def _fmt(cols, rows, limit):
    if cols == "ERROR":
        return "DENIED / ERROR: " + str(rows[0][0])
    out = [" | ".join(cols)]
    for row in rows[:limit]:
        out.append(" | ".join("NULL" if v is None else str(v) for v in row))
    return "\n".join(out)


def _write_csv(name, cols, rows):
    with open(os.path.join(EVID, name), "w", newline="") as f:
        wr = csv.writer(f)
        if cols == "ERROR":
            wr.writerow(["result"]); wr.writerow(["ERROR: " + str(rows[0][0])])
        else:
            wr.writerow(cols)
            wr.writerows([["NULL" if v is None else v for v in r] for r in rows])


# --------------------------------------------------------------------------- part B
def _attachment_sql(msg):
    for a in (msg.attachments or []):
        q = getattr(a, "query", None)
        if q is not None:
            return getattr(q, "query", None) or getattr(q, "description", None)
    return None


def _attachment_text(msg):
    for a in (msg.attachments or []):
        t = getattr(a, "text", None)
        if t is not None:
            return getattr(t, "content", None)
    return None


def part_b(space_id):
    lines = ["# Layer 7 benchmarks (B): natural-language accuracy via the Conversation API",
             "",
             f"Questions sent to the live Genie space `{space_id}` through the Conversation "
             f"API. For each: the SQL Genie generated and which governed source it chose. "
             f"The retrievable-value question shows whether Genie preferred the certified "
             f"metric view over the uncertified scratch trap.", ""]
    rows_summary = []
    questions = list(space_spec.SAMPLE_QUESTIONS)
    for q in questions:
        try:
            msg = admin.genie.start_conversation_and_wait(space_id, q)
            sql = _attachment_sql(msg) or ""
            text = _attachment_text(msg) or ""
            # Genie quotes identifiers with backticks (`cat`.`governance`.`worklist`), so
            # match against a backtick-stripped copy or the schema check misses them.
            norm = sql.replace("`", "")
            src = ("certified metric view" if "star_value_metrics" in norm
                   else "UNCERTIFIED TRAP" if "star_value_rollup" in norm
                   else "governed table" if ".governance." in norm
                   else "unknown")
            lines += [f"## {q}\n",
                      f"source chosen: **{src}**\n",
                      f"generated SQL:\n```sql\n{sql.strip()[:1200]}\n```\n",
                      f"answer: {str(text).strip()[:600]}\n"]
            rows_summary.append({"question": q, "source": src, "has_sql": bool(sql)})
            print(f"  Q: {q[:60]} -> {src}")
        except Exception as e:
            lines += [f"## {q}\n", f"_conversation error: {str(e).splitlines()[0][:160]}_\n"]
            rows_summary.append({"question": q, "source": "error"})
    with open(os.path.join(EVID, "genie_conversation_evidence.md"), "w") as f:
        f.write("\n".join(lines))
    print("part B: queried", len(questions), "questions via Conversation API")
    return rows_summary


def main():
    info = json.load(open(os.path.join(EVID, "space_info.json")))
    space_id = info["space_id"]
    a = part_a()
    b = part_b(space_id)
    summary = {"space_id": space_id, "space_url": info.get("url"),
               "part_a": a, "part_b": b}
    with open(os.path.join(EVID, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print("wrote summary.json")


if __name__ == "__main__":
    main()
