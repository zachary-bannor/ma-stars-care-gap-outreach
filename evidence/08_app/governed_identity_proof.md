# Layer 8: governed identity and least-privilege (serving path)

- Postgres `current_user`: `07369d4b-134b-42bb-b2aa-25c57456404d` (database `databricks_postgres`)
- Expected coordinator service principal: `07369d4b-134b-42bb-b2aa-25c57456404d` -> MATCH
- Contracts visible on the serving surface: ['H1234'] -> coordinator-scoped (H1234 only)
- Sample `member_id`: `M00075709` -> cleartext (coordinator entitlement)
- DELETE on `ops.worklist_status`: DENIED -> permission denied for table worklist_status

The Layer 3 Unity Catalog column masks and row filter enforce on the analytics path (the Layer 7 Genie space). On this Lakebase serving path coordinator-safety comes from the pre-minimized, contract-scoped serving surface plus this least-privilege Postgres role.
