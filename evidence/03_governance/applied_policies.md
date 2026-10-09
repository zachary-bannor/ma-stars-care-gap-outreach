# Applied column masks, row filters, and policy functions

## governance.care_gaps

```sql
CREATE TABLE zrb_fe_bar_uhc_stars_catalog.governance.care_gaps (
  member_id STRING COLLATE UTF8_BINARY MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_member_id`,
  contract_id STRING COLLATE UTF8_BINARY,
  plan_id STRING COLLATE UTF8_BINARY,
  measure_id STRING COLLATE UTF8_BINARY,
  star_weight INT,
  measurement_year INT,
  gap_status STRING COLLATE UTF8_BINARY,
  due_date DATE,
  birth_date DATE MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_birth_date`,
  age INT MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_age`,
  sex STRING COLLATE UTF8_BINARY,
  county STRING COLLATE UTF8_BINARY,
  dual_eligible BOOLEAN MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_dual`,
  is_diabetic INT,
  is_hypertensive INT)
USING delta
COMMENT 'Governed care-gap worklist. member_id/birth_date/dual_eligible masked by policy; row-filtered by contract.'
WITH ROW FILTER `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_rls_contract` ON (contract_id)
TBLPROPERTIES (
  'delta.checkpointPolicy' = 'v2',
  'delta.enableDeletionVectors' = 'true',
  'delta.enableRowTracking' = 'true',
  'delta.feature.appendOnly' = 'supported',
  'delta.feature.deletionVectors' = 'supported',
  'delta.feature.domainMetadata' = 'supported',
  'delta.feature.invariants' = 'supported',
  'delta.feature.rowTracking' = 'supported',
  'delta.feature.v2Checkpoint' = 'supported',
  'delta.minReaderVersion' = '3',
  'delta.minWriterVersion' = '7',
  'delta.parquet.compression.codec' = 'zstd',
  'delta.parquet.format.version' = '2.12.0',
  'delta.parquet.format.version.afe.internal' = '2.12.0')

```

## governance.member_labs

```sql
CREATE TABLE zrb_fe_bar_uhc_stars_catalog.governance.member_labs (
  member_id STRING COLLATE UTF8_BINARY MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_member_id`,
  contract_id STRING COLLATE UTF8_BINARY,
  loinc STRING COLLATE UTF8_BINARY,
  test_name STRING COLLATE UTF8_BINARY,
  result_value DOUBLE MASK `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_mask_clinical`,
  result_date DATE)
USING delta
COMMENT 'Governed lab readings. result_value clinically masked; member_id masked; row-filtered by contract.'
WITH ROW FILTER `zrb_fe_bar_uhc_stars_catalog`.`governance`.`fn_rls_contract` ON (contract_id)
TBLPROPERTIES (
  'delta.checkpointPolicy' = 'v2',
  'delta.enableDeletionVectors' = 'true',
  'delta.enableRowTracking' = 'true',
  'delta.feature.appendOnly' = 'supported',
  'delta.feature.deletionVectors' = 'supported',
  'delta.feature.domainMetadata' = 'supported',
  'delta.feature.invariants' = 'supported',
  'delta.feature.rowTracking' = 'supported',
  'delta.feature.v2Checkpoint' = 'supported',
  'delta.minReaderVersion' = '3',
  'delta.minWriterVersion' = '7',
  'delta.parquet.compression.codec' = 'zstd',
  'delta.parquet.format.version' = '2.12.0',
  'delta.parquet.format.version.afe.internal' = '2.12.0')

```

## Policy functions

### governance.fn_mask_age

```sql
CASE WHEN is_member('zrb_stars_phi_authorized') THEN a ELSE least(a, 90) END
```

### governance.fn_mask_birth_date

```sql
CASE WHEN is_member('zrb_stars_phi_authorized') THEN bd ELSE trunc(bd, 'YEAR') END
```

### governance.fn_mask_clinical

```sql
CASE WHEN is_member('zrb_stars_phi_authorized') THEN v ELSE NULL END
```

### governance.fn_mask_dual

```sql
CASE WHEN is_member('zrb_stars_phi_authorized') OR is_member('zrb_stars_quality_analysts') THEN b ELSE NULL END
```

### governance.fn_mask_member_id

```sql
CASE
  WHEN is_member('zrb_stars_phi_authorized') OR is_member('zrb_stars_care_coordinators') OR is_member('zrb_stars_admins') THEN mid
  ELSE sha2(mid, 256)
END
```

### governance.fn_rls_contract

```sql
is_member('zrb_stars_phi_authorized') OR is_member('zrb_stars_admins') OR is_member('zrb_stars_quality_analysts') OR is_member('zrb_stars_data_engineers')
  OR exists (
    SELECT 1 FROM governance.coordinator_scope s
    WHERE s.principal = current_user() AND s.contract_id = p_contract_id
  )
```
