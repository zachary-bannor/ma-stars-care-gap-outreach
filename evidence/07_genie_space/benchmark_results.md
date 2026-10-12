# Layer 7 benchmarks (A): governed correctness, masking, OntoRank contrast

Run as the quality-analyst service principal `9490fdb4-1a5e-42eb-b5a6-4ecab7d48337` against the governed surfaces. Access decisions come from the Layer 3 masks and row filter under this principal's identity, exactly as they will inside Genie.

## Curated example queries (analyst persona)

**What is the total retrievable Star-weighted value across all open care gaps?**

```
retrievable_value
42327.0
```

**Show the retrievable Star-weighted value and open-gap count by measure.**

```
measure_id | measure_name | retrievable_value | open_gaps
CBP | Controlling High Blood Pressure | 13959.0 | 25874
COL | Colorectal Cancer Screening | 10410.0 | 19313
MAD | Medication Adherence for Diabetes Medications | 9440.0 | 6353
EED | Eye Exam for Patients with Diabetes | 5335.0 | 9827
GSD | Glycemic Status Assessment for Patients with Diabetes | 3184.0 | 5835
```

**How many open care gaps are there in total, by measure?**

```
measure_id | open_gaps
CBP | 25874
COL | 19313
EED | 9827
MAD | 6353
GSD | 5835
```

**Which members have open diabetes gaps and the highest expected Star-weighted value?**

```
member_id | measure_id | measure_name | expected_value | propensity
12bf56bad9e69ed132989037569f72ef807ef27dfa1d9a5ce7fb82eb19dd2734 | MAD | Medication Adherence for Diabetes Medications | 2.642 | 0.8807339668273926
a680faaccc264bf13744546a4dbf1a69af494306f4827084dd78ab9751067618 | MAD | Medication Adherence for Diabetes Medications | 2.642 | 0.8807339668273926
3eedc8020982a9297fceb0a35867c56bb5ff000b225b66b0f87c0515e3e06d6c | MAD | Medication Adherence for Diabetes Medications | 2.642 | 0.8807339668273926
77d8475d93177cd4b9b3a5e7547492e91f5d6044efa041b3b066aaf44d484568 | MAD | Medication Adherence for Diabetes Medications | 2.642 | 0.8807339668273926
e17e8c44161efb04d5bca2cf36c84a2c8088260764378dd4ea75c9dfb42f55a6 | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
c3ce132aa308c103a1c1d08d438fddf5a456c01b1c36778bfec590d24984692e | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
b6d15853e7ea43fddeab106af9645084cfcda7c266a1cdebab36dc3bcdbbd132 | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
19e2c28667b4cc544383f9e33dd32d00dd5320a1f1878b42c8f48dcb8736abed | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
92d20985b85cdbfcb240f78bfce6c3116e40938a97a952b027437bad0c1b2590 | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
5eb2a99d4a37bc6feca6c16173bf1527281b22d184719473fb138261e293d0f3 | MAD | Medication Adherence for Diabetes Medications | 2.429 | 0.8095238208770752
```

**How many open CBP gaps are there on contract H1234?**

```
open_cbp_gaps
12920
```

**What is the total retrievable Star-weighted value in the active worklist?**

```
worklist_retrievable_value | members
1626.0 | 500
```

**How many members in the active worklist are we leading with medication adherence?**

```
lead_measure | lead_measure_name | members
MAD | Medication adherence for diabetes (MAD, triple-weighted) | 486
COL | Colorectal cancer screening (COL) | 6
CBP | Controlling blood pressure (CBP) | 5
GSD | Diabetes HbA1c blood-sugar lab (GSD) | 3
```

**Which members are we leading with a lower-value ask than their highest-value gap?**

```
member_id | lead_measure | lead_measure_name | lead_value | lead_confidence
66d5c3bc0a1c177999f80afbeb7bf96633006db221c734e3a181cfc95204a1c6 | GSD | Diabetes HbA1c blood-sugar lab (GSD) | 0.577 | 0.39
31c3c62903f2c14ce94ef31d046b7ab0281eaf7684998f6675d730eded235c78 | GSD | Diabetes HbA1c blood-sugar lab (GSD) | 0.577 | 0.39
483897bc3d1d6ecac0dfdf442339bb898e8a43e20d26937b1a21b2c4f3f80625 | GSD | Diabetes HbA1c blood-sugar lab (GSD) | 0.577 | 0.43
cbebcfd4dd26a73a3e152c762bc6969ae7c3140917cb0cb5d5969efe0d4db6c1 | CBP | Controlling blood pressure (CBP) | 0.614 | 0.42
e3a41d95899836f61093dc7a32c152b40a04458f7b04026401e5f401cc47b86b | CBP | Controlling blood pressure (CBP) | 0.612 | 0.53
```

**What is the average closure propensity for CBP gaps?**

```
avg_propensity
0.5395
```

**How many outreach drafts are pending human review, by measure?**

```
measure_id | drafts_pending_review
GSD | 50
EED | 50
CBP | 50
COL | 50
MAD | 50
```

**List the HEDIS measures and their Star weights.**

```
measure_id | measure_name | star_weight
MAD | Medication Adherence for Diabetes Medications | 3
CBP | Controlling High Blood Pressure | 1
COL | Colorectal Cancer Screening | 1
EED | Eye Exam for Patients with Diabetes | 1
GSD | Glycemic Status Assessment for Patients with Diabetes | 1
```

**What would we retrieve if we closed every open MAD medication-adherence gap?**

```
mad_retrievable_value | mad_open_gaps
9440.0 | 6353
```

## Benchmark assertions

- [PASS] What is the total number of open care gaps?  ->  got 67202, expected 67202
- [PASS] Open gaps by measure.  ->  got {'GSD': 5835, 'EED': 9827, 'CBP': 25874, 'COL': 19313, 'MAD': 6353}
- [PASS] Total retrievable Star-weighted value (certified).  ->  certified total = 42327.45
- [PASS] member_id must come back pseudonymized for the analyst persona.  ->  member_id=5a9d61225b4155ea...
- [PASS] The active worklist is bounded to the top members on the active contract.  ->  500 members, 1 contract(s)
- [PASS] ai_decide led some members with a lower-value ask than their top gap.  ->  count = 5

## Masking contrast (same query, two identities)

- break-glass member_id: `M00000001`
- analyst member_id:     `00001b2029db4841856554c10e39e053e0ad643f557132b972558975aea088c2`  (SHA-256 pseudonym, 64 hex chars)

## Certified vs uncertified retrievable value (why the source matters)

- certified metric view star_value_metrics: 42327.45
- uncertified scratch trap star_value_rollup: 200330.0

The trap flattens the MAD triple weight and counts non-open gaps, so its number is materially wrong. Genie must prefer the certified metric view.
