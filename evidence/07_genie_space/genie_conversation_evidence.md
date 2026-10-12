# Layer 7 benchmarks (B): natural-language accuracy via the Conversation API

Questions sent to the live Genie space `01f1c660da191d8fac9592c222cc0648` through the Conversation API **as the quality-analyst service principal** (granted CAN_RUN on the space in 03_create_space.py). Genie runs each generated query under this identity, so the Layer 3 masks and contract row filter apply to the NL path too: member ids come back pseudonymized in the answers below, exactly as a real analyst would see them. For each question: the SQL Genie generated and which governed source it chose. The retrievable-value question shows whether Genie preferred the certified metric view over the uncertified scratch trap.

## What is the total retrievable Star-weighted value across all open care gaps?

source chosen: **certified metric view**

generated SQL:
```sql
SELECT MEASURE(`retrievable_star_weighted_value`) AS `retrievable_star_weighted_value`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`star_value_metrics`
GROUP BY ALL
```

answer: The total **retrievable Star-weighted value** across all open care gaps is **42,327**. Based on the single result returned from `zrb_fe_bar_uhc_stars_catalog.governance.star_value_metrics`, the measured value is **42,327.44679412246**, which rounds to **42,327** for reporting.

## Show the retrievable Star-weighted value and open-gap count by measure.

source chosen: **certified metric view**

generated SQL:
```sql
SELECT
  `measure_id`,
  `measure_name`,
  MEASURE(`retrievable_star_weighted_value`) AS `retrievable_star_weighted_value`,
  MEASURE(`open_gap_count`) AS `open_gap_count`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`star_value_metrics`
WHERE `measure_id` IS NOT NULL
  AND `measure_name` IS NOT NULL
GROUP BY ALL
ORDER BY `retrievable_star_weighted_value` DESC
```

answer: Retrievable Star-weighted value is highest for **Controlling High Blood Pressure (CBP)** at **13,959** across **25,874** open gaps, followed by **Colorectal Cancer Screening (COL)** at **10,410** across **19,313** open gaps. Examples include:
- **CBP** — **13,959** retrievable Star-weighted value; **25,874** open gaps
- **COL** — **10,410** retrievable Star-weighted value; **19,313** open gaps
- **MAD** — **9,440** retrievable Star-weighted value; **6,353** open gaps
- **EED** — **5,335** retrievable Star-weighted value; **9,827** open gaps
- **GSD** — **3,184** retrievable Star-weighted value

## Which members have open diabetes gaps and the highest expected Star-weighted value?

source chosen: **governed table**

generated SQL:
```sql
SELECT member_id, measure_id, measure_name,
       ROUND(expected_weighted_value, 3) AS expected_value, propensity
FROM zrb_fe_bar_uhc_stars_catalog.governance.gap_scores
WHERE measure_id IN ('EED','GSD','MAD')
ORDER BY expected_weighted_value DESC
LIMIT 20
```

answer: Examples include these members with the **highest expected Star-weighted value** among the diabetes gaps returned:
- **12bf56ba...** — **MAD** (Medication Adherence for Diabetes Medications), **2.642**
- **a680faac...** — **MAD** (Medication Adherence for Diabetes Medications), **2.642**
- **3eedc802...** — **MAD** (Medication Adherence for Diabetes Medications), **2.642**
- **77d8475d...** — **MAD** (Medication Adherence for Diabetes Medications), **2.642**
- **e17e8c44...** — **MAD** (Medication Adherence for Diabetes Medications), **2.429**
Across all 20 rows returned, every top diabetes ga

## How many open CBP gaps are there on contract H1234?

source chosen: **certified metric view**

generated SQL:
```sql
SELECT MEASURE(`open_gap_count`) AS `open_cbp_gaps`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`star_value_metrics`
WHERE `measure_id` = 'CBP' AND `contract_id` = 'H1234'
GROUP BY ALL
```

answer: Contract **H1234** has **12,920** open **CBP** gaps. Based on the certified metrics view used here, the result set contains **1** row for **measure_id = CBP** and **contract_id = H1234**.

## What is the total retrievable Star-weighted value in the active worklist?

source chosen: **governed table**

generated SQL:
```sql
SELECT SUM(`member_ev`) AS `worklist_retrievable_value`, COUNT(*) AS `members`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`worklist`
```

answer: The total retrievable Star-weighted value in the active worklist is **1,626** across **500 members**. That equals about **3.3** retrievable Star-weighted value per member in the active worklist.

## How many members in the active worklist are we leading with medication adherence?

source chosen: **governed table**

generated SQL:
```sql
SELECT COUNT(*) AS `members`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`worklist`
WHERE `lead_measure` = 'MAD'
```

answer: **486 members** in the active worklist are being led with medication adherence (`lead_measure = MAD`). Based on the single result shown, the count for medication adherence leads is **486 members**.

## Which members are we leading with a lower-value ask than their highest-value gap, and why might that be?

source chosen: **governed table**

generated SQL:
```sql
SELECT member_id, lead_measure, lead_measure_name, ROUND(lead_ev, 3) AS lead_value, lead_confidence
FROM zrb_fe_bar_uhc_stars_catalog.governance.worklist
WHERE led_below_top_ev = true
ORDER BY member_ev DESC
```

answer: There are **5 members** on the worklist where the outreach lead is **not** their highest-value gap; in this result set, the lead ask is either **Diabetes HbA1c blood-sugar lab (GSD)** or **Controlling blood pressure (CBP)**. The visible data shows the lead ask values range from **0.577** to **0.614** with lead confidence from **0.39** to **0.53**, but it does **not** include each member’s actual highest-value gap or a reason field, so the only supported explanation is that these were deliberate sequencing choices flagged by **led_below_top_ev = true**.

- **66d5c3bc... (truncated)** — led with

## How many outreach drafts are pending human review, by measure?

source chosen: **governed table**

generated SQL:
```sql
SELECT `measure_id`, COUNT(*) AS `drafts_pending_review`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`outreach_drafts`
WHERE `requires_human_review` = true
  AND `measure_id` IS NOT NULL
GROUP BY `measure_id`
ORDER BY `drafts_pending_review` DESC
```

answer: There are **5 measures** with outreach drafts pending human review, and each has **50** drafts pending review. 
- **COL:** 50
- **GSD:** 50
- **MAD:** 50
- **CBP:** 50
- **EED:** 50
This sample shows the pending human-review workload is **evenly distributed** across all measures shown.
