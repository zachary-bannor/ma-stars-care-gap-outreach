# Layer 2 evidence: Lakeflow care-gap pipeline

Catalog `zrb_fe_bar_uhc_stars_catalog`. Pipeline full-refreshed, gold re-derives HEDIS gaps independently from bronze claims/labs/fills.

## Row counts

| Table | Rows |
| --- | --- |
| `bronze.medical_claims` | 308,610 |
| `bronze.pharmacy_fills` | 215,248 |
| `bronze.member_roster` | 100,000 |
| `bronze.lab_results` | 150,546 |
| `bronze.providers` | 400 |
| `bronze.outreach_history` | 90,250 |
| `silver.members` | 100,000 |
| `silver.pdc` | 22,609 |
| `silver.prior_outreach` | 59,666 |
| `gold.care_gaps` | 200,330 |
| `gold.measure_weights` | 5 |

## Re-derived open gaps vs Layer 1 target

Layer 2 never receives the gap flags. These counts are re-derived from raw claims, labs, and fills, so landing on Layer 1's intended totals proves the layers are connected.

| Measure | Intended (Layer 1) | Re-derived (Layer 2) | Delta |
| --- | --- | --- | --- |
| EED | 9,827 | 9,827 | +0 |
| GSD | 5,835 | 5,835 | +0 |
| CBP | 25,874 | 25,874 | +0 |
| COL | 19,313 | 19,313 | +0 |
| MAD | 6,353 | 6,353 | +0 |
| **total** | **67,202** | **67,202** | **+0** |

## DQ expectations (most recent update)

| Dataset | Expectation | Passed | Failed |
| --- | --- | --- | --- |
| `zrb_fe_bar_uhc_stars_catalog.bronze.lab_results` | valid_member_id | 150,546 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.lab_results` | valid_result_date | 150,546 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.medical_claims` | valid_claim_status | 308,610 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.medical_claims` | valid_member_id | 308,610 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.medical_claims` | valid_service_date | 308,610 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.member_roster` | valid_birth_date | 100,000 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.member_roster` | valid_member_id | 100,000 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.outreach_history` | valid_member_id | 90,250 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.outreach_history` | valid_outcome | 90,250 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.pharmacy_fills` | valid_days_supply | 215,248 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.pharmacy_fills` | valid_fill_date | 215,248 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.pharmacy_fills` | valid_member_id | 215,248 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.bronze.providers` | valid_provider_id | 400 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.gold.care_gaps` | valid_gap_status | 200,330 | 0 |
| `zrb_fe_bar_uhc_stars_catalog.gold.care_gaps` | valid_measure | 200,330 | 0 |
