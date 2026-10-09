# Layer 6 / Lakebase worklist run evidence

Lakebase instance `zrb-stars-worklist` (CU_1, PG_VERSION_16, AVAILABLE) serves the ranked care-coordinator worklist with transactional outreach write-back. The worklist is built in the lakehouse (`zrb_fe_bar_uhc_stars_catalog.ops.member_worklist`), synced into Postgres as `zrb_fe_bar_uhc_stars_catalog.ops.worklist` (SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE), and written back to through two native Postgres tables registered in Unity Catalog.

## Ranking vs sequencing

The worklist holds the top 500 members by `member_ev` (sum of their open-gap expected Star-weighted values from Layer 4). That EV ranking is the exec-defensible number and is never changed. On top of it, `ai_decide` chose, per member, which measure to LEAD the next contact with and whether to bundle a second ask, batch-materialized into worklist columns with confidence and per-option probabilities.

| metric | value |
|---|---|
| members in worklist | 500 |
| open gaps covered | 1565 |
| mean lead confidence | 0.861 |
| bundle rate | 0.894 |
| out-of-set fallbacks | 0 |
| ai_decide errors | 0 |
| lead differs from pure top-EV | 6 members |
| drafts attached (Layer 5 segments) | 249 / 500 |

Lead-measure distribution: MAD 486, COL 6, CBP 5, GSD 3.
MAD leads the top of the worklist because the highest-EV members carry the triple-weighted adherence gap; the sequencing diverges from pure EV where an easier or channel-fit ask is the better first contact (6 members, see sequencing_divergence.csv).

## Governed posture

The worklist projection is column-minimized to coordinator-entitled fields (member_id cleartext, EV, measures, propensity, channel, tenure, lead decision, draft). No birth_date, clinical values, dual flag or sex leave the lakehouse into Postgres. Postgres persona roles mirror the Layer 3 UC grants: the coordinator reads the worklist and writes the log, the analyst is read-only.

## Transactional write-back

See writeback_proof.md and writeback_actions.csv. Connected as the care-coordinator service principal, a single transaction appended an outreach action and advanced the status to `contacted`; a rolled-back update left the status intact; an ungranted DELETE was denied; and the committed write-back is readable through Unity Catalog (1 action row(s), 1 status(es) advanced), reaching the governed lakehouse and Genie with no reverse ETL.
