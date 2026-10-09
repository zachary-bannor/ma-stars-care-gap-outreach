# Layer 3 enforcement proof

The same three queries, run under three real principals against the governed consumption zone. Access decisions come entirely from each principal's workspace group membership through the UC column-mask and row-filter engine.

## breakglass  (`zachary.bannor@databricks.com`)

**Row filter: contracts visible**
```
    contract_id | gaps
    H1234 | 99746
    H5678 | 60970
    H9012 | 39614
```

**Column masks: member_id / birth_date / dual_eligible**
```
    member_id | contract_id | measure_id | gap_status | birth_date | age | dual_eligible
    M00090159 | H5678 | EED | closed | 1961-08-25 | 65 | true
    M00042497 | H1234 | EED | closed | 1961-03-27 | 65 | false
    M00059278 | H5678 | EED | closed | 1961-01-21 | 65 | false
    M00071076 | H5678 | EED | closed | 1961-01-13 | 65 | false
    M00001483 | H5678 | EED | closed | 1961-04-15 | 65 | false
```

**Clinical mask + table grant**
```
    member_id | loinc | result_value
    M00000005 | 4548-04-01 | 9.3
    M00000004 | 4548-04-01 | 7.0
    M00000006 | 4548-04-01 | 6.8
    M00000001 | 4548-04-01 | 7.1
    M00000007 | 4548-04-01 | 6.1
```

## coordinator  (`07369d4b-134b-42bb-b2aa-25c57456404d`)

**Row filter: contracts visible**
```
    contract_id | gaps
    H1234 | 99746
```

**Column masks: member_id / birth_date / dual_eligible**
```
    member_id | contract_id | measure_id | gap_status | birth_date | age | dual_eligible
    M00087315 | H1234 | EED | closed | 1961-01-01 | 65 | NULL
    M00042497 | H1234 | EED | closed | 1961-01-01 | 65 | NULL
    M00011983 | H1234 | EED | closed | 1961-01-01 | 65 | NULL
    M00095344 | H1234 | EED | closed | 1961-01-01 | 65 | NULL
    M00000277 | H1234 | EED | closed | 1961-01-01 | 65 | NULL
```

**Clinical mask + table grant**
```
DENIED / ERROR: [INSUFFICIENT_PERMISSIONS] Insufficient privileges:
User does not have SELECT on Table 'zrb_fe_bar_uhc_stars_catalog.governance.member_labs'. SQLSTATE: 42501
```

## analyst  (`9490fdb4-1a5e-42eb-b5a6-4ecab7d48337`)

**Row filter: contracts visible**
```
    contract_id | gaps
    H1234 | 99746
    H5678 | 60970
    H9012 | 39614
```

**Column masks: member_id / birth_date / dual_eligible**
```
    member_id | contract_id | measure_id | gap_status | birth_date | age | dual_eligible
    9d62e54d6f4aa1f372545ddcf5a73db691fc6afd3395da7a1b6025d87adfb193 | H5678 | EED | closed | 1961-01-01 | 65 | true
    ff94634f41e363dfd5d4a1a0d3a2014bfe5e10d8a1599c5ee4530584f5eff7ae | H1234 | EED | closed | 1961-01-01 | 65 | false
    23f6b4dd91d92eedf602920097da695204dcc690acf0061bd1d6cc67dde740aa | H5678 | EED | closed | 1961-01-01 | 65 | false
    4a5812dff9a92fa038f280bd186934596620cbc6f2f8c8743156bdeb5dd28af0 | H5678 | EED | closed | 1961-01-01 | 65 | false
    1bd5dce434a70de92d3e8ab085817579a65ddb32c06838b7ed617a13483446e5 | H5678 | EED | closed | 1961-01-01 | 65 | false
```

**Clinical mask + table grant**
```
    member_id | loinc | result_value
    c2945b48032f3225f70ea2b1d4b80a68f2fb425caf872cb51006f3e3a13141fc | 4548-04-01 | NULL
    5e2e31dc8fa497f499dc02e1575ad335efc1989a9964e790332856533a588f0c | 4548-04-01 | NULL
    fc294d67a4634022443c37229a6205cfecba6c627e6f5de01f4fb275c5f5fd4e | 4548-04-01 | NULL
    6c9f65424a601b60ca6b9a3ad23bb48bfbf0d1f54e29d60ede37944d9a1e107c | 4548-04-01 | NULL
    8ccc75023c3e9f2ffca5400e0433ff537099b9a994f05b0c66758fc14ab9f870 | 4548-04-01 | NULL
```
