# Layer 6 transactional write-back proof

Connected to Lakebase Postgres as the care-coordinator service principal `07369d4b-134b-42bb-b2aa-25c57456404d` (zrb_stars_governance_tester), the same identity proven under Layer 3 Unity Catalog enforcement.

- **point_read**: member=M00075709 rank=1 lead=MAD conf=0.94 bundle=bundle bundle_measure=CBP
- **status_before**: null
- **txn_commit**: INSERT coordinator_action + UPSERT worklist_status -> contacted
- **status_after**: {"status": "contacted", "last_action": "called", "updated_by": "07369d4b-134b-42bb-b2aa-25c57456404d"}
- **txn_rollback**: UPDATE ->closed then ROLLBACK; status remained contacted
- **least_privilege_denial**: DELETE denied: permission denied for table worklist_status
- **uc_round_trip**: 1 write-back row(s) visible via Unity Catalog

The atomic commit landed, the rolled-back update left the prior state intact, the ungranted DELETE was denied by Postgres (least privilege), and the committed write-back was immediately readable through Unity Catalog with no reverse ETL.
