#!/usr/bin/env python3
"""Mint OAuth M2M secrets for the persona service principals that
04_prove_enforcement.py authenticates as. Writes /tmp/tester_creds.json
(care-coordinator SP) and /tmp/analyst_creds.json (quality-analyst SP).

This script contains no secrets; it generates them at run time. The minted
credential files live under /tmp (outside the repo) and are never committed;
delete them once the proof has run. Run locally after 01_identities.py:

    python3 src/03_governance/01b_mint_persona_secrets.py

The SP scim ids come from 01_identities.py's output. Update them here if the
identities are recreated.
"""
import json
import subprocess

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
HOST = "https://fevm-zrb-fe-bar-uhc-stars.cloud.databricks.com"

# persona -> (SP scim id, SP application_id). Match 01_identities.py output.
SPS = {
    "tester":  ("77434984440632", "07369d4b-134b-42bb-b2aa-25c57456404d"),   # care-coordinator SP
    "analyst": ("78409112002589", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337"),   # quality-analyst SP
}

for persona, (scim_id, app_id) in SPS.items():
    out = subprocess.run(
        ["databricks", "service-principal-secrets-proxy", "create", scim_id,
         "-p", PROFILE, "-o", "json"],
        capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    path = f"/tmp/{persona}_creds.json"
    json.dump({"host": HOST, "client_id": app_id,
               "client_secret": d["secret"], "secret_id": d["id"]}, open(path, "w"))
    print(f"minted {persona} secret -> {path}")
