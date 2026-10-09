#!/usr/bin/env python3
"""Layer 5 / GenAI outreach drafting: provision the governed Unity AI Gateway endpoint.

Runs locally as the workspace admin (same local-admin pattern as Layer 3's
01_identities.py and Layer 4's 00_setup_grants.py):

    python3 src/05_genai_drafting/00_setup_gateway.py

Stands up a DEDICATED Unity AI Gateway endpoint, `zrb-stars-outreach-gateway`,
that fronts the workspace's own Databricks-hosted Claude Foundation Model
endpoint (default Claude Sonnet 5.5, the current-generation model). It is an
external-model endpoint with provider `databricks-model-serving`: the only way
to put our own governed front door (guardrails + rate limit + usage tracking +
payload logging) in front of a Databricks-hosted Claude without reconfiguring the
shared system endpoint for the whole workspace. The AI Gateway block carries:

  - guardrails: safety on input and output, plus PII detection set to BLOCK. The
    drafting prompt is designed to carry no PHI, so PII-BLOCK is a true safety
    net: if an identifier ever reached a request or a draft, the gateway stops it.
  - rate_limits: 60 calls / minute (endpoint key), a real cost + abuse control.
  - usage_tracking: enabled (lands in the system serving usage tables).
  - inference_table: payload logging to zrb_fe_bar_uhc_stars_catalog.ops, the
    auditable request/response record (usage tracking the evidence can read).

The endpoint authenticates downstream to the inner Claude endpoint with an
on-behalf-of token minted for the engineer / pipeline service principal, stored
in a Databricks secret scope and referenced (never inlined). So generation routes
through the gateway as the engineer identity, consistent with Layers 3 and 4.
Idempotent: creates on first run, updates config + ai_gateway on reruns.
"""
import json
import sys

from databricks.sdk import WorkspaceClient

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
WORKSPACE_URL = "https://fevm-zrb-fe-bar-uhc-stars.cloud.databricks.com"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
WAREHOUSE = "3c261b5b5dfe9c21"

INNER_ENDPOINT = "databricks-claude-sonnet-5-5"   # current-generation Claude on the gateway
GW_ENDPOINT = "zrb-stars-outreach-gateway"
ENGINEER_SP = "e42fda52-f9e2-478c-b4a4-abba32a1b601"  # zrb_stars_pipeline_sp application_id

SECRET_SCOPE = "zrb_stars_outreach"
SECRET_KEY = "gw_sp_token"
INFER_SCHEMA = "ops"
INFER_PREFIX = "outreach_gateway"
TOKEN_LIFETIME_SECONDS = 90 * 24 * 3600  # 90 days, covers the 60-day sandbox TTL

w = WorkspaceClient(profile=PROFILE)


def api(method, path, body=None):
    return w.api_client.do(method, path, body=body or {})


# --- 0. Operational schema for the inference (payload-logging) table ---------
# The gateway writes the payload log into this schema; it must exist first.
w.statement_execution.execute_statement(
    warehouse_id=WAREHOUSE, catalog=CATALOG, wait_timeout="30s",
    statement=f"CREATE SCHEMA IF NOT EXISTS {INFER_SCHEMA} "
              "COMMENT 'Operational logs: Unity AI Gateway inference (payload) tables.'")
print(f"· schema {CATALOG}.{INFER_SCHEMA} ready")

# --- 1. Secret scope ---------------------------------------------------------
try:
    w.secrets.create_scope(scope=SECRET_SCOPE)
    print(f"· created secret scope {SECRET_SCOPE}")
except Exception as e:
    if "RESOURCE_ALREADY_EXISTS" in str(e):
        print(f"· secret scope {SECRET_SCOPE} already exists")
    else:
        raise

# --- 2. Downstream auth token for the engineer / pipeline SP -----------------
# Preferred: an on-behalf-of token so the gateway calls Claude AS the engineer SP
# (least privilege, documented Layer 3/4 identity). Falls back to a self token if
# on-behalf-of is not permitted; raises clearly if tokens are disabled entirely
# (there is no raw-model-call fallback by design).
token = None
try:
    resp = api("POST", "/api/2.0/token-management/on-behalf-of/tokens", {
        "application_id": ENGINEER_SP,
        "comment": "zrb-stars-outreach-gateway downstream auth (engineer SP)",
        "lifetime_seconds": TOKEN_LIFETIME_SECONDS,
    })
    token = resp.get("token_value")
    print("· minted on-behalf-of token for engineer SP")
except Exception as e:
    print(f"· on-behalf-of token unavailable ({str(e).splitlines()[0][:90]}); trying a self token")
    try:
        resp = api("POST", "/api/2.0/token/create", {
            "comment": "zrb-stars-outreach-gateway downstream auth (workspace admin fallback)",
            "lifetime_seconds": TOKEN_LIFETIME_SECONDS,
        })
        token = resp.get("token_value")
        print("· minted self token (admin); gateway calls Claude as the admin identity")
    except Exception as e2:
        raise SystemExit(
            "Could not mint any token for the gateway's downstream auth. Personal access "
            f"tokens may be disabled in this workspace. Error: {str(e2).splitlines()[0]}")

if not token:
    raise SystemExit("Token mint returned no token_value; cannot configure the gateway.")

w.secrets.put_secret(scope=SECRET_SCOPE, key=SECRET_KEY, string_value=token)
print(f"· stored token at secrets/{SECRET_SCOPE}/{SECRET_KEY}")

# --- 3. Endpoint config + AI Gateway block -----------------------------------
served_config = {
    "served_entities": [{
        "name": "claude",
        "external_model": {
            "name": INNER_ENDPOINT,
            "provider": "databricks-model-serving",
            "task": "llm/v1/chat",
            "databricks_model_serving_config": {
                "databricks_workspace_url": WORKSPACE_URL,
                "databricks_api_token": "{{secrets/%s/%s}}" % (SECRET_SCOPE, SECRET_KEY),
            },
        },
    }],
}

ai_gateway = {
    "usage_tracking_config": {"enabled": True},
    "inference_table_config": {
        "enabled": True,
        "catalog_name": CATALOG,
        "schema_name": INFER_SCHEMA,
        "table_name_prefix": INFER_PREFIX,
    },
    "rate_limits": [{"calls": 60, "renewal_period": "minute", "key": "endpoint"}],
    "guardrails": {
        "input": {"safety": True, "pii": {"behavior": "BLOCK"}},
        "output": {"safety": True, "pii": {"behavior": "BLOCK"}},
    },
}

exists = True
try:
    current = api("GET", f"/api/2.0/serving-endpoints/{GW_ENDPOINT}")
except Exception as e:
    if "RESOURCE_DOES_NOT_EXIST" in str(e) or "does not exist" in str(e):
        exists = False
    else:
        raise

if not exists:
    print(f"· creating endpoint {GW_ENDPOINT}")
    current = api("POST", "/api/2.0/serving-endpoints", {
        "name": GW_ENDPOINT, "config": served_config, "ai_gateway": ai_gateway})
else:
    print(f"· endpoint {GW_ENDPOINT} exists; updating config + ai_gateway")
    api("PUT", f"/api/2.0/serving-endpoints/{GW_ENDPOINT}/config", served_config)
    api("PUT", f"/api/2.0/serving-endpoints/{GW_ENDPOINT}/ai-gateway", ai_gateway)
    current = api("GET", f"/api/2.0/serving-endpoints/{GW_ENDPOINT}")

# --- 4. Let the engineer SP query the gateway --------------------------------
ep_id = current.get("id")
if ep_id:
    try:
        api("PATCH", f"/api/2.0/permissions/serving-endpoints/{ep_id}", {
            "access_control_list": [
                {"service_principal_name": ENGINEER_SP, "permission_level": "CAN_QUERY"}]})
        print(f"· granted CAN_QUERY on {GW_ENDPOINT} to the engineer SP")
    except Exception as e:
        print(f"· (CAN_QUERY grant skipped: {str(e).splitlines()[0][:90]})")

# --- 5. Report ---------------------------------------------------------------
gw = current.get("ai_gateway", {})
print("\nGateway ready:")
print(json.dumps({
    "endpoint": GW_ENDPOINT,
    "routes_to": INNER_ENDPOINT,
    "state": current.get("state"),
    "guardrails": gw.get("guardrails"),
    "rate_limits": gw.get("rate_limits"),
    "usage_tracking": gw.get("usage_tracking_config"),
    "inference_table": gw.get("inference_table_config"),
}, indent=2, default=str))
