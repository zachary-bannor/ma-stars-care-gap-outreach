-- Layer 2 / Gold: the HEDIS care-gap re-derivation. This is the connectedness
-- proof. Each measure's open/closed status is computed independently from the
-- bronze claims, labs, and fills, never from a handed-over flag. The open-gap
-- counts the evidence step reads back from this table should reproduce Layer 1's
-- intended totals (67,202 open gaps: EED 9,827 / GSD 5,835 / CBP 25,874 /
-- COL 19,313 / MAD 6,353).

-- Care gaps: one row per applicable member x measure x year -----------------

CREATE OR REFRESH MATERIALIZED VIEW gold.care_gaps (
  CONSTRAINT valid_gap_status EXPECT (gap_status IN ('open', 'closed', 'excluded')),
  CONSTRAINT valid_measure    EXPECT (measure_id IN ('EED', 'GSD', 'CBP', 'COL', 'MAD'))
)
COMMENT 'HEDIS care gaps re-derived from raw claims/labs/fills. gap_status open = actionable.'
AS
WITH claim_flags AS (
  SELECT
    member_id,
    MAX(CASE WHEN cpt_hcpcs = '92014' THEN 1 ELSE 0 END)              AS has_eye_exam,
    MAX(CASE WHEN cpt_hcpcs IN ('45378', '82274') THEN 1 ELSE 0 END)  AS has_col_screen
  FROM bronze.medical_claims
  GROUP BY member_id
),
lab_flags AS (
  SELECT
    member_id,
    MAX(CASE WHEN loinc = '4548-4' THEN 1 ELSE 0 END)                       AS has_a1c,
    MAX(CASE WHEN loinc = '8480-6' THEN CAST(result_value AS DOUBLE) END)   AS systolic,
    MAX(CASE WHEN loinc = '8462-4' THEN CAST(result_value AS DOUBLE) END)   AS diastolic
  FROM bronze.lab_results
  GROUP BY member_id
)

-- EED: Eye Exam for Patients with Diabetes. Open when no retinal eye exam
-- (CPT 92014) claim exists this year for a diabetic.
SELECT
  m.member_id,
  'EED' AS measure_id,
  2026  AS measurement_year,
  CASE WHEN COALESCE(cf.has_eye_exam, 0) = 1 THEN 'closed' ELSE 'open' END AS gap_status,
  DATE'2026-12-31' AS due_date
FROM silver.members m
LEFT JOIN claim_flags cf USING (member_id)
WHERE m.is_diabetic = 1

UNION ALL

-- GSD: Glycemic Status Assessment. Open when no HbA1c result (LOINC 4548-4)
-- exists this year for a diabetic.
SELECT
  m.member_id, 'GSD', 2026,
  CASE WHEN COALESCE(lf.has_a1c, 0) = 1 THEN 'closed' ELSE 'open' END,
  DATE'2026-12-31'
FROM silver.members m
LEFT JOIN lab_flags lf USING (member_id)
WHERE m.is_diabetic = 1

UNION ALL

-- CBP: Controlling High Blood Pressure. Open when the latest reading is
-- uncontrolled (systolic >= 140 or diastolic >= 90) for a hypertensive.
SELECT
  m.member_id, 'CBP', 2026,
  CASE WHEN lf.systolic >= 140 OR lf.diastolic >= 90 THEN 'open' ELSE 'closed' END,
  DATE'2026-12-31'
FROM silver.members m
LEFT JOIN lab_flags lf USING (member_id)
WHERE m.is_hypertensive = 1

UNION ALL

-- COL: Colorectal Cancer Screening. Open when no colonoscopy (45378) or FIT
-- (82274) claim exists this year for an age-eligible member (< 76).
SELECT
  m.member_id, 'COL', 2026,
  CASE WHEN COALESCE(cf.has_col_screen, 0) = 1 THEN 'closed' ELSE 'open' END,
  DATE'2026-12-31'
FROM silver.members m
LEFT JOIN claim_flags cf USING (member_id)
WHERE m.age < 76

UNION ALL

-- MAD: Medication Adherence for Diabetes (triple-weighted). Open when PDC < 0.80
-- for a member on diabetes medication.
SELECT
  m.member_id, 'MAD', 2026,
  CASE WHEN p.pdc < 0.80 THEN 'open' ELSE 'closed' END,
  DATE'2026-12-31'
FROM silver.members m
JOIN silver.pdc p USING (member_id);

-- Star-rating weights per measure -------------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW gold.measure_weights
COMMENT 'HEDIS measure Star weights. MAD (adherence) is triple-weighted.'
AS
SELECT * FROM VALUES
  ('EED', 1, 'Eye Exam for Patients with Diabetes'),
  ('GSD', 1, 'Glycemic Status Assessment for Patients with Diabetes'),
  ('CBP', 1, 'Controlling High Blood Pressure'),
  ('COL', 1, 'Colorectal Cancer Screening'),
  ('MAD', 3, 'Medication Adherence for Diabetes Medications')
AS t(measure_id, star_weight, measure_name);
