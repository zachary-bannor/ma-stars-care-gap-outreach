-- Layer 2 / Bronze: typed ingestion of the raw files Layer 1 landed in the
-- bronze.raw_landing volume. Claims and pharmacy fills arrive as month-partitioned
-- folders and are read with Auto Loader as STREAMING tables (the freshness story:
-- a new month's file appends incrementally without reprocessing history). Roster,
-- labs, providers, and prior-year outreach are reference/batch sources read as
-- materialized views.
--
-- Every table carries DQ EXPECT constraints. These keep the rows (no drop) and
-- record passed/failed counts to the pipeline event log, which the evidence step
-- reads back as committed text. ${care_gap_catalog} is substituted from the
-- pipeline configuration so the read path follows the target catalog.

-- Streaming: medical claims -------------------------------------------------

CREATE OR REFRESH STREAMING TABLE bronze.medical_claims (
  CONSTRAINT valid_member_id   EXPECT (member_id RLIKE '^M[0-9]{8}$'),
  CONSTRAINT valid_service_date EXPECT (service_date IS NOT NULL),
  CONSTRAINT valid_claim_status EXPECT (claim_status IN ('paid', 'denied', 'pending'))
)
COMMENT 'Medical claims, Auto Loader stream over month-partitioned raw files.'
AS SELECT
  claim_id,
  member_id,
  CAST(service_date AS DATE) AS service_date,
  provider_id,
  place_of_service,
  cpt_hcpcs,
  icd10_dx,
  claim_status,
  month AS service_month,
  _metadata.file_path AS _source_file
FROM STREAM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/medical_claims',
  format => 'csv',
  header => true,
  schemaHints => 'service_date date'
);

-- Streaming: pharmacy fills -------------------------------------------------

CREATE OR REFRESH STREAMING TABLE bronze.pharmacy_fills (
  CONSTRAINT valid_member_id  EXPECT (member_id RLIKE '^M[0-9]{8}$'),
  CONSTRAINT valid_fill_date  EXPECT (fill_date IS NOT NULL),
  CONSTRAINT valid_days_supply EXPECT (days_supply > 0)
)
COMMENT 'Pharmacy fills, Auto Loader stream over month-partitioned raw files.'
AS SELECT
  rx_id,
  member_id,
  CAST(fill_date AS DATE) AS fill_date,
  ndc,
  drug_class,
  CAST(days_supply AS INT) AS days_supply,
  CAST(refill_number AS INT) AS refill_number,
  month AS fill_month,
  _metadata.file_path AS _source_file
FROM STREAM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/pharmacy_fills',
  format => 'csv',
  header => true,
  schemaHints => 'fill_date date'
);

-- Batch: member roster ------------------------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW bronze.member_roster (
  CONSTRAINT valid_member_id EXPECT (member_id RLIKE '^M[0-9]{8}$'),
  CONSTRAINT valid_birth_date EXPECT (birth_date IS NOT NULL)
)
COMMENT 'Member roster reference table.'
AS SELECT *
FROM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/member_roster',
  format => 'csv',
  header => true
);

-- Batch: lab results --------------------------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW bronze.lab_results (
  CONSTRAINT valid_member_id  EXPECT (member_id RLIKE '^M[0-9]{8}$'),
  CONSTRAINT valid_result_date EXPECT (result_date IS NOT NULL)
)
COMMENT 'Lab results (HbA1c and blood-pressure readings).'
AS SELECT
  lab_id,
  member_id,
  CAST(result_date AS DATE) AS result_date,
  loinc,
  test_name,
  result_value
FROM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/lab_results',
  format => 'csv',
  header => true
);

-- Batch: providers ----------------------------------------------------------

CREATE OR REFRESH MATERIALIZED VIEW bronze.providers (
  CONSTRAINT valid_provider_id EXPECT (provider_id IS NOT NULL)
)
COMMENT 'Provider directory.'
AS SELECT *
FROM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/providers',
  format => 'csv',
  header => true
);

-- Batch: prior-year outreach history (ML training labels) -------------------

CREATE OR REFRESH MATERIALIZED VIEW bronze.outreach_history (
  CONSTRAINT valid_member_id EXPECT (member_id RLIKE '^M[0-9]{8}$'),
  CONSTRAINT valid_outcome   EXPECT (outcome IN ('closed', 'no_response', 'declined', 'unreachable'))
)
COMMENT 'Prior-year outreach attempts and outcomes; closure is the ML training label.'
AS SELECT
  outreach_id,
  member_id,
  measure_id,
  channel,
  CAST(attempt_ts AS DATE) AS attempt_ts,
  outcome,
  coordinator_id,
  next_action
FROM read_files(
  '/Volumes/${care_gap_catalog}/bronze/raw_landing/outreach_history',
  format => 'csv',
  header => true
);
