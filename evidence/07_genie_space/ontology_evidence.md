# Layer 7 ontology evidence

The Genie Ontology for this space is not a toggle; it is the Unity Catalog metadata Genie consumes automatically: a declared entity-relationship graph (PK/FK), a certified metric view, certification tags that drive OntoRank authority, and curated comments. This is that metadata, read back from information_schema.

## constraints

Declared relationship graph (PK/FK). These are what Genie Ontology reads as certified entity keys and join paths.

| table_name | constraint_name | constraint_type |
| --- | --- | --- |
| care_gaps | fk_care_gaps_measure | FOREIGN KEY |
| care_gaps | fk_care_gaps_member | FOREIGN KEY |
| gap_scores | pk_gap_scores | PRIMARY KEY |
| gap_scores | fk_gap_scores_measure | FOREIGN KEY |
| gap_scores | fk_gap_scores_member | FOREIGN KEY |
| measure_weights | pk_measure_weights | PRIMARY KEY |
| member_dim | pk_member_dim | PRIMARY KEY |
| outreach_drafts | fk_drafts_measure | FOREIGN KEY |
| outreach_drafts | fk_drafts_member | FOREIGN KEY |
| worklist | pk_worklist | PRIMARY KEY |
| worklist | fk_worklist_lead_measure | FOREIGN KEY |
| worklist | fk_worklist_member | FOREIGN KEY |

## foreign keys

Foreign-key column mappings (child column -> referenced dimension).

| child_table | child_column | parent_table | parent_column | constraint_name |
| --- | --- | --- | --- | --- |
| care_gaps | measure_id | measure_weights | measure_id | fk_care_gaps_measure |
| care_gaps | member_id | member_dim | member_id | fk_care_gaps_member |
| gap_scores | measure_id | measure_weights | measure_id | fk_gap_scores_measure |
| gap_scores | member_id | member_dim | member_id | fk_gap_scores_member |
| outreach_drafts | measure_id | measure_weights | measure_id | fk_drafts_measure |
| outreach_drafts | member_id | member_dim | member_id | fk_drafts_member |
| worklist | lead_measure | measure_weights | measure_id | fk_worklist_lead_measure |
| worklist | member_id | member_dim | member_id | fk_worklist_member |

## metric views

Certified metric view(s): the authoritative measure definitions.

| table_schema | table_name | table_type |
| --- | --- | --- |
| governance | star_value_metrics | METRIC_VIEW |

## certification tags

Certification tags = the OntoRank authority signal. Governed surfaces + metric view are certified; the scratch trap is deprecated.

| catalog_name | schema_name | table_name | tag_name | tag_value |
| --- | --- | --- | --- | --- |
| zrb_fe_bar_uhc_stars_catalog | governance | care_gaps | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | gap_scores | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | measure_weights | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | member_dim | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | member_labs | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | outreach_drafts | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | star_value_metrics | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | governance | worklist | system.certification_status | certified |
| zrb_fe_bar_uhc_stars_catalog | analytics_sandbox | star_value_rollup | system.certification_status | deprecated |

## table comments

Table semantics Genie reads.

| table_schema | table_name | comment |
| --- | --- | --- |
| analytics_sandbox | star_value_rollup | Star value rollup by measure (legacy quality-dashboard source). Totals gaps and Star value across the book. |
| governance | care_gaps | Governed care-gap worklist. member_id/birth_date/dual_eligible masked by policy; row-filtered by contract. |
| governance | coordinator_scope | Row-level security assignment map for care coordinators (lookup-driven RLS). |
| governance | gap_scores | Scored open care gaps: per member x open HEDIS measure, the calibrated closure propensity and expected Star-weighted value (EV = propensity x star_weight), the exec-ranked retrievable-value proxy. member_id pseudonymized; row-filtered by contract. Certified. |
| governance | measure_weights | Measure dimension: the five HEDIS Star measures, their CMS Star weight (MAD triple-weighted) and display names. Public reference, certified. |
| governance | member_dim | Member entity dimension: one governed row per Medicare Advantage member. member_id pseudonymized, birth_date generalized to year, age capped at 90, dual-eligible analyst-visible; row-filtered by contract. |
| governance | member_labs | Governed lab readings. result_value clinically masked; member_id masked; row-filtered by contract. |
| governance | outreach_drafts | Governed outreach drafts worklist. member_id masked by policy; row-filtered by contract. Human-review only. |
| governance | star_value_metrics | Certified Star-value metric view: the authoritative retrievable Star-weighted value, open-gap and member counts, and average closure propensity over scored open gaps, by measure / contract / Star weight. Prefer this over any ad-hoc rollup. |
| governance | worklist | Active prioritized coordinator worklist (top-500 members by member_ev on the active contract) with the ai_decide lead-outreach decision. member_ev is the sum of a member open-gap expected Star-weighted values. led_below_top_ev marks members ai_decide led with a lower-EV ask than their top gap. member_id pseudonymized; row-filtered by contract. Certified. |
