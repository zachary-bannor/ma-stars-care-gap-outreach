-- Layer 2 / Silver: member feature tables. The condition cohort is recovered
-- independently from claims (Layer 1 emits a management-visit claim for every
-- diabetic and hypertensive), so silver never receives a handed-over gap flag.

-- Member features + condition flags ----------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW silver.members
COMMENT 'One row per member: demographics, propensity features, derived condition flags.'
AS
WITH dx AS (
  SELECT
    member_id,
    MAX(CASE WHEN icd10_dx = 'E11.9' THEN 1 ELSE 0 END) AS is_diabetic,
    MAX(CASE WHEN icd10_dx = 'I10'   THEN 1 ELSE 0 END) AS is_hypertensive
  FROM bronze.medical_claims
  GROUP BY member_id
)
SELECT
  r.member_id,
  r.contract_id,
  r.plan_id,
  r.sex,
  r.county,
  CAST(r.birth_date AS DATE) AS birth_date,
  -- Age as of the measurement year end. Computed as (year - birth year) rather
  -- than datediff/365.25: the measurement anchor is Dec 31, so every member's
  -- birthday has already occurred, and calendar-year subtraction is exact. A
  -- days/365.25 floor would drift one year low for late-year birthdays because
  -- of accumulated leap days.
  (2026 - year(CAST(r.birth_date AS DATE))) AS age,
  CAST(r.dual_eligible AS BOOLEAN)             AS dual_eligible,
  CAST(r.digital_channel_on_file AS BOOLEAN)   AS digital_channel_on_file,
  CAST(r.tenure_months AS INT)                 AS tenure_months,
  CAST(r.distance_to_provider_miles AS DOUBLE) AS distance_to_provider_miles,
  COALESCE(dx.is_diabetic, 0)     AS is_diabetic,
  COALESCE(dx.is_hypertensive, 0) AS is_hypertensive
FROM bronze.member_roster r
LEFT JOIN dx USING (member_id);

-- Diabetes medication adherence (PDC) --------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW silver.pdc
COMMENT 'Proportion of days covered for diabetes medications, measurement-year denominator.'
AS
SELECT
  member_id,
  COUNT(*)                       AS fill_count,
  SUM(days_supply)               AS covered_days,
  -- PDC with a fixed measurement-year (365-day) denominator, capped at 1.0.
  -- Layer 1 places each 30-day fill in a distinct month, so this reproduces the
  -- intended adherent/non-adherent split cleanly: adherent members land 10-12
  -- fills (PDC 0.82-0.99), non-adherent 4-9 fills (PDC 0.33-0.74). The 0.80
  -- MAD threshold separates them with no overlap.
  LEAST(1.0, SUM(days_supply) / 365.0) AS pdc
FROM bronze.pharmacy_fills
WHERE drug_class = 'Oral Antidiabetics'
GROUP BY member_id;

-- Prior-year outreach response (ML feature) --------------------------------

CREATE OR REFRESH MATERIALIZED VIEW silver.prior_outreach
COMMENT 'Per-member prior-year outreach volume and closure rate; a model feature, not a gap input.'
AS
SELECT
  member_id,
  COUNT(*)                                              AS prior_attempts,
  SUM(CASE WHEN outcome = 'closed' THEN 1 ELSE 0 END)   AS prior_closures,
  AVG(CASE WHEN outcome = 'closed' THEN 1.0 ELSE 0.0 END) AS prior_closure_rate
FROM bronze.outreach_history
GROUP BY member_id;
