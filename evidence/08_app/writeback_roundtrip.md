# Layer 8: transactional write-back round-trip (the app's path)

Target member: `M00075709`

- Status before: `{'member_id': 'M00075709', 'status': 'contacted', 'last_action': 'called', 'next_action_due': datetime.datetime(2026, 10, 12, 19, 27, 1, 873785, tzinfo=zoneinfo.ZoneInfo(key='GMT')), 'updated_by': '07369d4b-134b-42bb-b2aa-25c57456404d', 'updated_at': datetime.datetime(2026, 10, 9, 19, 27, 1, 873785, tzinfo=zoneinfo.ZoneInfo(key='GMT'))}`
- Status after: `{'member_id': 'M00075709', 'status': 'contacted', 'last_action': 'called', 'next_action_due': None, 'updated_by': '07369d4b-134b-42bb-b2aa-25c57456404d', 'updated_at': datetime.datetime(2026, 10, 12, 18, 25, 18, 280451, tzinfo=zoneinfo.ZoneInfo(key='GMT'))}`
- Write-back committed: True

The app appends one row to `ops.coordinator_action` and upserts `ops.worklist_status` in a single transaction (rollback on error). This is the identical SQL the Streamlit app runs on 'Save action'.
