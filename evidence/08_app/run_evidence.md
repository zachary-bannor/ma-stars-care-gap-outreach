# Layer 8: Databricks App (coordinator worklist) run evidence

The app reads the prioritized worklist from the Lakebase serving table `ops.worklist` and records outreach transactionally to `ops.coordinator_action` and `ops.worklist_status`, all as the governed coordinator service principal.

## Checks

- identity_is_coordinator_sp: True
- worklist_rows: 500
- contract_scope_H1234_only: True
- member_id_cleartext: True
- delete_denied: True
- writeback_roundtrip: True

## Deployed app

- name: zrb-stars-coordinator
- url: https://zrb-stars-coordinator-7474649467662043.aws.databricksapps.com
- status: {'message': 'App compute is running.', 'state': 'ACTIVE'}
- service principal: app-4fntvm zrb-stars-coordinator (f0256d93-7f9c-4a4a-aaa7-5c649b215b78)

See worklist_sample.csv, governed_identity_proof.md, writeback_roundtrip.md, app_info.json, summary.json.
