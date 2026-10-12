# MA Stars care-gap analytics: semantic data dictionary

Business-glossary content for the Genie space, intended for a Unity Catalog Page.
It is schema and semantics only. No member rows, no identifiers, nothing regulated,
because Pages store plain text and can replicate globally. Everything here describes
the governed star schema the VP-Stars space reads.

## What this space answers

Medicare Advantage Star and HEDIS care-gap questions for a quality manager or VP of
Stars: how many gaps are open, how much Star-weighted value is still retrievable this
measurement year, and which members the outreach worklist should work first. Reaching
4.0 Stars on a contract unlocks the CMS Quality Bonus Payment, the dollar cliff that
funds this work.

## Entities and how they relate

The governed zone is a star schema. Two dimensions anchor it and the facts reference
them through declared Unity Catalog foreign keys.

- **member_dim** (dimension, one row per member). The member entity. Key: member_id, a
  SHA-256 pseudonym for this persona. Carries contract, plan, generalized demographics,
  dual-eligible, preferred channel and tenure band.
- **measure_weights** (dimension, five rows). The measure entity. Key: measure_id.
  Holds each HEDIS measure's display name and CMS Star weight.
- **gap_scores** (fact). One row per member x open measure. Closure propensity and the
  expected Star-weighted value. References member_dim and measure_weights.
- **worklist** (fact). The active prioritized queue, top-500 members by member_ev on
  contract H1234, with the ai_decide lead-outreach decision. References member_dim.
- **care_gaps** (fact). The full gap inventory across all statuses.
- **outreach_drafts** (fact). Human-review GenAI outreach drafts for top gaps.

## The five HEDIS measures

- **EED**: diabetic retinal eye exam. Weight 1. A diabetes measure.
- **GSD**: HbA1c blood-sugar lab for members with diabetes. Weight 1. A diabetes measure.
- **CBP**: controlling high blood pressure. Weight 1. The hypertension measure.
- **COL**: colorectal cancer screening. Weight 1.
- **MAD**: medication adherence for diabetes medications. Weight 3, CMS triple-weighted.
  A diabetes measure, and the single largest per-closure lever on the Star score.

"Diabetes gaps" means EED, GSD and MAD together. "Blood pressure" means CBP.
"Colorectal" or "colon" means COL. "Adherence" or "medication" means MAD.

## Key terms

- **Open gap**: an actionable, not-yet-closed measure for a member this measurement year.
- **star_weight**: the CMS weight of a measure. MAD is 3, the rest are 1.
- **expected_weighted_value (EV)**: calibrated closure propensity x Star weight. The
  exec-defensible proxy for the Star-weighted value retrievable by closing that gap.
- **retrievable Star-weighted value**: the sum of EV over open scored gaps. The lever.
- **member_ev**: a member's EV summed over their open gaps. The worklist ranks on this.
- **active worklist**: the top-500 members by member_ev on contract H1234.
- **lead_measure**: the single measure the ai_decide model chose to lead a member's next
  contact with. **led_below_top_ev** is true when that lead was not the member's single
  highest-value gap, a deliberate sequencing judgment.

## The authoritative source for value

The certified metric view **star_value_metrics** is the one authoritative definition of
retrievable Star-weighted value, open-gap and member counts, and average closure
propensity. Prefer it for any total, count or value question. The uncertified
analytics_sandbox.star_value_rollup is a legacy scratch rollup that computes Star value
incorrectly (it flattens the MAD triple weight and counts closed gaps). It is not for
official numbers.
