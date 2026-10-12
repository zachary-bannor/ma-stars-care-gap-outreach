"""Layer 8 setup (LOCAL, run as a workspace admin before `databricks bundle deploy`).

Creates the Databricks secret scope that holds the coordinator service principal's
OAuth secret, mints that secret, and stores it. The app reads it at runtime via the
secret resource declared on the app in resources/08_app.app.yml (valueFrom), so the
secret never lives in code or in the repo.

Run:
    python3 src/08_app/00_setup_app.py

Then:
    databricks bundle deploy -t dev -p fe-vm-zrb-fe-bar-uhc-stars
    databricks bundle run coordinator_app -t dev -p fe-vm-zrb-fe-bar-uhc-stars
"""
import json
import subprocess
import sys

from databricks.sdk import WorkspaceClient

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
SCOPE = "zrb_stars_app"
KEY = "coord_sp_secret"
# Coordinator service principal (zrb_stars_governance_tester): SCIM id for secret
# minting, application id used as the Postgres user at runtime.
COORD_SCIM_ID = "77434984440632"


MAX_SP_SECRETS = 5  # Databricks caps a service principal at five OAuth secrets.


def _proxy(subcommand, *extra):
    """Run `databricks service-principal-secrets-proxy <subcommand> <scim> [extra...]`.
    The SCIM id always follows the subcommand (delete also takes the secret id after)."""
    return subprocess.run(
        ["databricks", "service-principal-secrets-proxy", subcommand, COORD_SCIM_ID,
         *extra, "-p", PROFILE, "--output", "json"],
        capture_output=True, text=True, check=True,
    )


def prune_oldest_if_full():
    """The coordinator SP accumulates OAuth secrets across layer builds and is capped at
    five. If it is full, delete the oldest so this mint can succeed on a rerun."""
    secrets = json.loads(_proxy("list").stdout)
    if len(secrets) < MAX_SP_SECRETS:
        return
    # Sort a missing create_time last (not first), so a timestamp-less secret is never
    # mistaken for the oldest and evicted ahead of genuinely older credentials.
    oldest = min(secrets, key=lambda s: s.get("create_time") or "9999")
    _proxy("delete", oldest["id"])
    print(f"pruned oldest coordinator SP secret {oldest['id'][:12]}... to stay under the "
          f"{MAX_SP_SECRETS}-secret cap")


def mint_coord_secret():
    """Mint an OAuth secret for the coordinator SP via the secrets proxy (same path
    Layer 6 used). The secret value is returned, never printed."""
    prune_oldest_if_full()
    r = _proxy("create")
    return json.loads(r.stdout)["secret"]


def main():
    w = WorkspaceClient(profile=PROFILE)

    existing = {s.name for s in w.secrets.list_scopes()}
    if SCOPE not in existing:
        w.secrets.create_scope(scope=SCOPE)
        print(f"created secret scope {SCOPE}")
    else:
        print(f"secret scope {SCOPE} already exists")

    secret = mint_coord_secret()
    w.secrets.put_secret(scope=SCOPE, key=KEY, string_value=secret)
    print(f"stored coordinator SP OAuth secret at {SCOPE}/{KEY}")
    print("setup complete; deploy the bundle next (the app resource grants its SP READ "
          "on this secret).")


if __name__ == "__main__":
    sys.exit(main())
