# Layer 7 benchmarks (B): natural-language accuracy via the Conversation API

Questions sent to the live Genie space `01f1c660da191d8fac9592c222cc0648` through the Conversation API. For each: the SQL Genie generated and which governed source it chose. The retrievable-value question shows whether Genie preferred the certified metric view over the uncertified scratch trap.

## What is the total retrievable Star-weighted value across all open care gaps?

source chosen: **certified metric view**

generated SQL:
```sql
SELECT MEASURE(`retrievable_star_weighted_value`) AS `retrievable_star_weighted_value`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`star_value_metrics`
GROUP BY ALL
```

answer: The total **retrievable Star-weighted value** across all open care gaps is **42,327**. Based on the single result returned, the current recoverable opportunity is **42,327** in Star-weighted value.

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

answer: Across the **5 measures** shown, **Controlling High Blood Pressure (CBP)** has the largest retrievable Star-weighted value at **13,959** with **25,874** open gaps, followed by **Colorectal Cancer Screening (COL)** at **10,410** with **19,313** open gaps. Examples include:
- **CBP** — retrievable Star-weighted value **13,959**; open gaps **25,874**
- **COL** — retrievable Star-weighted value **10,410**; open gaps **19,313**
- **MAD** — retrievable Star-weighted value **9,440**; open gaps **6,353**
- **EED** — retrievable Star-weighted value **5,335**; open gaps **9,827**
- **GSD** — retrievable

## Which members have open diabetes gaps and the highest expected Star-weighted value?

source chosen: **governed table**

generated SQL:
```sql
SELECT member_id, measure_id, measure_name, ROUND(expected_weighted_value, 3) AS expected_value, propensity
FROM zrb_fe_bar_uhc_stars_catalog.governance.gap_scores
WHERE measure_id IN ('EED','GSD','MAD')
ORDER BY expected_weighted_value DESC
LIMIT 20
```

answer: Examples of members with the **highest expected Star-weighted value** for diabetes gaps in this result are:
- **M00062066** — **MAD** (Medication Adherence for Diabetes Medications), expected value **2.642**
- **M00058154** — **MAD** (Medication Adherence for Diabetes Medications), expected value **2.642**
- **M00010226** — **MAD** (Medication Adherence for Diabetes Medications), expected value **2.642**
- **M00012433** — **MAD** (Medication Adherence for Diabetes Medications), expected value **2.642**
- **M00036125** — **MAD** (Medication Adherence for Diabetes Medications), expected value **

## How many open CBP gaps are there on contract H1234?

source chosen: **certified metric view**

generated SQL:
```sql
SELECT MEASURE(`open_gap_count`) AS `open_cbp_gaps`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`star_value_metrics`
WHERE `measure_id` = 'CBP' AND `contract_id` = 'H1234'
GROUP BY ALL
```

answer: Contract **H1234** has **12,920** open **CBP** gaps. This result reflects the certified Star value metrics view for **measure_id = CBP** and **contract_id = H1234**.

## What is the total retrievable Star-weighted value in the active worklist?

source chosen: **governed table**

generated SQL:
```sql
SELECT SUM(`member_ev`) AS `worklist_retrievable_value`, COUNT(*) AS `members`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`worklist`
```

answer: The active worklist has a total retrievable Star-weighted value of **1,626** across **500** members. That means the current outreach worklist represents **1,626** in recoverable Star-weighted opportunity.

## How many members in the active worklist are we leading with medication adherence?

source chosen: **governed table**

generated SQL:
```sql
SELECT COUNT(*) AS `members`
FROM `zrb_fe_bar_uhc_stars_catalog`.`governance`.`worklist`
WHERE `lead_measure` = 'MAD'
```

answer: **486 members** in the active worklist are being led with medication adherence, where `lead_measure = 'MAD'`. Based on the single result shown, medication adherence is the lead outreach focus for **486 worklist members**.

## Which members are we leading with a lower-value ask than their highest-value gap, and why might that be?

source chosen: **governed table**

generated SQL:
```sql
SELECT member_id, lead_measure, lead_measure_name,
       ROUND(lead_ev, 3) AS lead_value, lead_confidence
FROM zrb_fe_bar_uhc_stars_catalog.governance.worklist
WHERE led_below_top_ev = true
ORDER BY member_ev DESC
```

answer: There are **5 members** in the current worklist where the outreach lead is **not** their highest-value gap. Examples include:
- **M00013603** — led with **Diabetes HbA1c blood-sugar lab (GSD)**, lead value **0.577**, confidence **0.39**
- **M00068060** — led with **Diabetes HbA1c blood-sugar lab (GSD)**, lead value **0.577**, confidence **0.39**
- **M00025806** — led with **Diabetes HbA1c blood-sugar lab (GSD)**, lead value **0.577**, confidence **0.43**
- **M00042225** — led with **Controlling blood pressure (CBP)**, lead value **0.614**, confidence **0.42**
- **M00026887** — led with **Contr

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

answer: Pending human review drafts are **evenly split across 5 measures**, with **50 drafts each**.

- **GSD:** 50
- **EED:** 50
- **CBP:** 50
- **COL:** 50
- **MAD:** 50

There is **no variation by measure** in the results shown.
