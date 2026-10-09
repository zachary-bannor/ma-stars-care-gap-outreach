# Layer 3 grant inventory

Least-privilege grant model. Business personas (coordinator, analyst) hold no privileges on the raw medallion; they read the governed consumption zone only. No `PUBLIC` grants; no `ALL_PRIVILEGES` outside the owner/admin. Grants target the persona service principals because this sandbox identity cannot create UC-grantable account groups (see 02b_grants_account_groups.sql for the production group model). Principal ids are annotated with the persona they represent.

## CATALOG `zrb_fe_bar_uhc_stars_catalog`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | USE CATALOG | CATALOG | zrb_fe_bar_uhc_stars_catalog | data-engineer SP (zrb_stars_pipeline_sp) |
| 07369d4b-134b-42bb-b2aa-25c57456404d | USE CATALOG | CATALOG | zrb_fe_bar_uhc_stars_catalog | care-coordinator SP (zrb_stars_governance_tester) |
| 9490fdb4-1a5e-42eb-b5a6-4ecab7d48337 | USE CATALOG | CATALOG | zrb_fe_bar_uhc_stars_catalog | quality-analyst SP (zrb_stars_analyst_sp) |
| aec5be3d-de3c-404c-8e60-feed0f265fd3 | ALL PRIVILEGES | CATALOG | zrb_fe_bar_uhc_stars_catalog | deployer SP (catalog owner) |
| aec5be3d-de3c-404c-8e60-feed0f265fd3 | MANAGE | CATALOG | zrb_fe_bar_uhc_stars_catalog | deployer SP (catalog owner) |
| zachary.bannor@databricks.com | ALL PRIVILEGES | CATALOG | zrb_fe_bar_uhc_stars_catalog | admin + break-glass (current user) |
| zachary.bannor@databricks.com | MANAGE | CATALOG | zrb_fe_bar_uhc_stars_catalog | admin + break-glass (current user) |

## SCHEMA `zrb_fe_bar_uhc_stars_catalog.bronze`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | MODIFY | SCHEMA | zrb_fe_bar_uhc_stars_catalog.bronze | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | SELECT | SCHEMA | zrb_fe_bar_uhc_stars_catalog.bronze | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.bronze | data-engineer SP (zrb_stars_pipeline_sp) |

## SCHEMA `zrb_fe_bar_uhc_stars_catalog.silver`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | MODIFY | SCHEMA | zrb_fe_bar_uhc_stars_catalog.silver | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | SELECT | SCHEMA | zrb_fe_bar_uhc_stars_catalog.silver | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.silver | data-engineer SP (zrb_stars_pipeline_sp) |

## SCHEMA `zrb_fe_bar_uhc_stars_catalog.gold`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | MODIFY | SCHEMA | zrb_fe_bar_uhc_stars_catalog.gold | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | SELECT | SCHEMA | zrb_fe_bar_uhc_stars_catalog.gold | data-engineer SP (zrb_stars_pipeline_sp) |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.gold | data-engineer SP (zrb_stars_pipeline_sp) |

## SCHEMA `zrb_fe_bar_uhc_stars_catalog.governance`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| e42fda52-f9e2-478c-b4a4-abba32a1b601 | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.governance | data-engineer SP (zrb_stars_pipeline_sp) |
| 07369d4b-134b-42bb-b2aa-25c57456404d | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.governance | care-coordinator SP (zrb_stars_governance_tester) |
| 9490fdb4-1a5e-42eb-b5a6-4ecab7d48337 | USE SCHEMA | SCHEMA | zrb_fe_bar_uhc_stars_catalog.governance | quality-analyst SP (zrb_stars_analyst_sp) |

## TABLE `zrb_fe_bar_uhc_stars_catalog.governance.care_gaps`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| 07369d4b-134b-42bb-b2aa-25c57456404d | SELECT | TABLE | zrb_fe_bar_uhc_stars_catalog.governance.care_gaps | care-coordinator SP (zrb_stars_governance_tester) |
| 9490fdb4-1a5e-42eb-b5a6-4ecab7d48337 | SELECT | TABLE | zrb_fe_bar_uhc_stars_catalog.governance.care_gaps | quality-analyst SP (zrb_stars_analyst_sp) |

## TABLE `zrb_fe_bar_uhc_stars_catalog.governance.member_labs`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
| 9490fdb4-1a5e-42eb-b5a6-4ecab7d48337 | SELECT | TABLE | zrb_fe_bar_uhc_stars_catalog.governance.member_labs | quality-analyst SP (zrb_stars_analyst_sp) |

## TABLE `zrb_fe_bar_uhc_stars_catalog.governance.coordinator_scope`

| Principal | ActionType | ObjectType | ObjectKey | Persona |
| --- | --- | --- | --- | --- |
