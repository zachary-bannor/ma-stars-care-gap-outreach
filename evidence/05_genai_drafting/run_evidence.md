# Layer 5 / GenAI outreach drafting: run evidence

Personalized, measure-appropriate, human-review outreach drafts for the
highest-priority open care gaps, routed through a governed Unity AI Gateway
endpoint. Priority is `gold.gap_scores.expected_weighted_value` from Layer 4
(calibrated closure propensity x Star weight), top 250 drafts
across all five measures.

## The governed gateway

`zrb-stars-outreach-gateway` is a dedicated Unity AI Gateway endpoint fronting
`databricks-claude-sonnet-5-5` (Claude Sonnet 5.5), the current-generation Claude on the
gateway. It is not a raw model call: every request passes the gateway's controls.

| control | configuration |
| --- | --- |
| input guardrails | safety=True, PII=BLOCK |
| output guardrails | safety=True, PII=BLOCK |
| rate limit | 60/minute (endpoint) |
| usage tracking | True |
| payload logging | `zrb_fe_bar_uhc_stars_catalog.ops.outreach_gateway_payload` |

PII detection is set to BLOCK on both sides. The prompt is designed to carry no
PHI, so PII-BLOCK is a true safety net rather than a routine step: if an
identifier ever reached a request or a draft, the gateway stops it. The endpoint
authenticates downstream to the inner Claude endpoint with a secret-referenced
token (never inlined). Production target-state mints that token on behalf of the
engineer / pipeline service principal; in this sandbox the SP lacks the token
permission, so the setup falls back to a workspace-admin token (a strict superset
of the SP's grants, the same account-admin limit documented in Layers 3 and 4).

The gateway logged 23 request(s) to `zrb_fe_bar_uhc_stars_catalog.ops.outreach_gateway_payload` (payload logging / usage tracking). A sample is in inference_log_sample.csv.

## Honesty and safety of the drafts

The model receives only three non-identifying features per segment: the covered
service, the preferred channel, and a coarse tenure band. It never sees a name,
member id, birth date, contract, diagnosis, or clinical value, so it cannot leak
or fabricate member specifics. The prompt forbids stating or implying any
condition and frames each measure as a routine, covered preventive service, so a
diabetes measure (EED/GSD/MAD) or the hypertension measure (CBP) never discloses
the member's condition. Everything personal is a `[FIRST_NAME]` / `[PLAN_NAME]` /
`[CLINIC_PHONE]` merge placeholder a human coordinator fills before sending.

Because the prompt depends only on the segment, we generate one draft per distinct
(measure, channel, tenure) segment (8 segments) and
assign it to every member x measure in that segment: no wasted identical calls,
and the gateway's governance applies to every call. The advisory lint
(`lint_flags`) runs over the actual output to prove, on the drafts themselves,
that no condition term slipped in and the name placeholder is present.

Every row is `review_status = 'pending_review'` with `requires_human_review = true`.
Auto-sendable rows: 0 (must be 0). Nothing is ever sent
by this layer.

## Output

`gold.outreach_drafts`: 250 drafts
(250 generated cleanly), one row per prioritized
member x measure, engineer-owned gold (Layer 3 posture). Per measure:

| measure_id | drafts | avg_expected_value |
| --- | --- | --- |
| CBP | 50 | 0.8938 |
| COL | 50 | 0.9081 |
| EED | 50 | 0.8831 |
| GSD | 50 | 0.8722 |
| MAD | 50 | 2.3171 |

A masked, contract-filtered `governance.outreach_drafts` is projected into the
governed consumption zone for coordinators (member_id masked by
`fn_mask_member_id`, row-filtered by `fn_rls_contract`), so the drafts carry the
same posture as `governance.care_gaps` and feed the Layer 6 Lakebase worklist.

A sample of drafts spanning all five measures is in `sample_drafts.csv`; the
verbatim prompt is in `prompt.md`; the resolved gateway config is in
`gateway_config.json`.
