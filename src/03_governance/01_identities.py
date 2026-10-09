#!/usr/bin/env python3
"""Layer 3 / Identities. Creates the workspace groups and service principals the
governance model grants against, then wires up membership. Run locally (SCIM admin
work, not an in-cluster step):

    python3 src/03_governance/01_identities.py

Idempotent: existing groups/SPs are reused. Prints a JSON block of the ids the
downstream governance and evidence steps need. Credentials are never printed here;
the persona service principals' OAuth secrets are minted separately by
01b_mint_persona_secrets.py.
"""
import json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
w = WorkspaceClient(profile=PROFILE)

# Least-privilege persona groups. Named for the project so they never collide with
# other tenants on the shared metastore.
GROUPS = [
    "zrb_stars_care_coordinators",   # frontline outreach; gold consumption zone, contract-scoped
    "zrb_stars_quality_analysts",    # population analytics; pseudonymized member ids
    "zrb_stars_data_engineers",      # pipeline/platform; medallion MODIFY
    "zrb_stars_phi_authorized",      # break-glass clinical access; bypasses masks + filters
    "zrb_stars_admins",              # governance owners
]

# Machine identities. Each persona the UC grant model targets is a real service
# principal: the pipeline SP (data engineer) runs automated writes, and the
# coordinator + analyst SPs are never-privileged principals used to prove
# enforcement end to end. Break-glass + admin are the current user.
SPS = ["zrb_stars_pipeline_sp", "zrb_stars_governance_tester", "zrb_stars_analyst_sp"]


def ensure_group(name):
    for g in w.groups.list(filter=f'displayName eq "{name}"'):
        return g.id
    return w.groups.create(display_name=name).id


def ensure_sp(name):
    for sp in w.service_principals.list(filter=f'displayName eq "{name}"'):
        return sp.id, sp.application_id
    sp = w.service_principals.create(display_name=name, active=True)
    return sp.id, sp.application_id


def add_member(group_id, member_scim_id):
    """Idempotent SCIM add of one member to a group."""
    g = w.groups.get(group_id)
    existing = {m.value for m in (g.members or [])}
    if member_scim_id in existing:
        return
    w.groups.patch(
        id=group_id,
        operations=[iam.Patch(
            op=iam.PatchOp.ADD, path="members",
            value=[{"value": member_scim_id}])],
        schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP],
    )


def main():
    me = w.current_user.me()
    gids = {name: ensure_group(name) for name in GROUPS}
    sps = {}
    for name in SPS:
        scim_id, app_id = ensure_sp(name)
        sps[name] = {"scim_id": scim_id, "application_id": app_id}

    # Membership wiring (least privilege).
    add_member(gids["zrb_stars_admins"], me.id)
    add_member(gids["zrb_stars_phi_authorized"], me.id)
    add_member(gids["zrb_stars_data_engineers"], sps["zrb_stars_pipeline_sp"]["scim_id"])
    add_member(gids["zrb_stars_care_coordinators"], sps["zrb_stars_governance_tester"]["scim_id"])
    add_member(gids["zrb_stars_quality_analysts"], sps["zrb_stars_analyst_sp"]["scim_id"])

    out = {
        "user": {"id": me.id, "userName": me.user_name},
        "groups": gids,
        "service_principals": sps,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
