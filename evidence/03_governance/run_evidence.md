# Layer 3 run evidence: Unity Catalog governance

Production payer governance posture over the care-gap medallion: least-privilege
grants, real UC column masks and row filters, lookup-driven row-level security,
governed sensitivity classification, lineage, and an end-to-end enforcement proof
run under three real principals.

## What was applied

Catalog `zrb_fe_bar_uhc_stars_catalog`, applied by the `governance_job` bundle job
(`src/03_governance/02_apply_governance.py`, idempotent, serverless).

- **Governed consumption zone** (`governance` schema): two managed Delta serving
  tables, `care_gaps` (coordinator/analyst worklist) and `member_labs` (clinical
  readings), carrying the enforced masks and row filters. The raw medallion is
  materialized views and streaming tables owned by the Lakeflow pipeline, which UC
  will not let masks attach to directly, so the enforced surface is this Delta zone
  and the medallion is locked to engineers / break-glass / admin.
- **Policy functions**: `fn_mask_member_id`, `fn_mask_birth_date`,
  `fn_mask_clinical`, `fn_mask_dual`, `fn_rls_contract`. Each keys on native
  `is_member()` over the persona workspace groups; the row filter also reads the
  `coordinator_scope` lookup table.
- **Row-level security**: `governance.coordinator_scope` maps a coordinator
  principal to its assigned contracts; `fn_rls_contract` trims a coordinator to
  those contracts and leaves analysts / engineers / break-glass / admins
  unrestricted.
- **Classification tags** (38): conformed to this metastore's governed tag
  policies, `sensitivity` (pii/internal/public), the `class.<entity>` PII-entity
  presence tags, `gov_data_domain`, `fs_tier`, `system.certification_status`, plus a
  free-form `care_gap_data_class` for the finer semantic class.
- **Least-privilege grants**: no `PUBLIC` grants, no `ALL_PRIVILEGES` outside the
  owner/admin, business personas kept off the raw medallion.

## Two deployment realities worth stating

1. **Masks live in the consumption zone, not on the medallion.** `ALTER TABLE ...
   SET MASK` is rejected on the pipeline-owned materialized views
   (`EXPECT_TABLE_NOT_VIEW`). The faithful payer pattern is therefore to lock the
   medallion to trusted roles and expose masked, row-filtered managed Delta serving
   tables, which is what `governance.care_gaps` / `member_labs` are.
2. **Grants target service principals, not groups.** UC grants resolve only
   account-level principals, and the build identity is a workspace admin, not an
   account admin, so UC-grantable account groups cannot be created here (grants to
   workspace-local groups fail `PRINCIPAL_DOES_NOT_EXIST`). Each persona is therefore
   a real service principal, granted directly. The mask / row-filter policy still
   uses native `is_member()` over the persona groups the SPs belong to. The
   production group-based grant model is committed verbatim as
   `src/03_governance/02b_grants_account_groups.sql`; promoting it is a one-step
   change once an account admin creates the five groups.

## Enforcement proof (`enforcement_summary.md`, `enforcement_*.csv`)

The same three queries run under three real principals. Access decisions come
entirely from each principal's group membership through the UC engine.

| | contracts visible | member_id | birth_date | dual_eligible | member_labs |
| --- | --- | --- | --- | --- | --- |
| break-glass (`zrb_stars_phi_authorized`) | all 3 | cleartext | real date | real | real values |
| coordinator (`zrb_stars_care_coordinators`, scoped H1234) | H1234 only | cleartext | year only | NULL | SELECT denied |
| analyst (`zrb_stars_quality_analysts`) | all 3 | SHA-256 pseudonym | year only | real | NULL (clinically masked) |

The coordinator-vs-analyst contrast is the decisive signal: two non-privileged
service principals, differing only in group membership, get different masked views
of the same table, so the enforcement is group-driven and not an admin bypass. The
coordinator's row count (99,746 gaps, contract H1234 only) matches the row filter;
the coordinator's denial on `member_labs` matches the grant model.

## Evidence files

- `grants.md` — per-object grant inventory with persona annotations.
- `tag_inventory.csv` — all 38 catalog/schema/table/column classification tags.
- `applied_policies.md` — `SHOW CREATE TABLE` showing the inline `MASK` and
  `WITH ROW FILTER` clauses, plus every policy-function definition.
- `lineage.csv` — 13 UC lineage edges, the full bronze to silver to gold to
  governance chain.
- `enforcement_summary.md` + `enforcement_<persona>_<query>.csv` — the three-persona
  proof result sets.

## Reproduce

```
databricks bundle deploy -t dev -p fe-vm-zrb-fe-bar-uhc-stars
databricks bundle run governance_job -t dev -p fe-vm-zrb-fe-bar-uhc-stars
python3 src/03_governance/03_evidence.py          # inventory evidence
python3 src/03_governance/04_prove_enforcement.py # enforcement proof
```

Identities are created once by `src/03_governance/01_identities.py`; the two
service-principal OAuth secrets used by the proof are minted out of band and never
committed.
