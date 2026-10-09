# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 1: Synthetic Data Generator
# MAGIC
# MAGIC Medicare Advantage Star-rating care-gap outreach. Everything here is **synthetic**.
# MAGIC No real UnitedHealthcare data, records, or identifiers. `member_id` is a generated
# MAGIC surrogate; there are no names, addresses, SSNs, or any PHI-shaped field.
# MAGIC
# MAGIC This notebook seeds a senior MA population, generates the raw source files a payer
# MAGIC would actually land (roster, medical claims, pharmacy fills, lab results, providers,
# MAGIC and a prior-year labeled outreach history for model training), and writes them as
# MAGIC files into a Unity Catalog volume. Layer 2 (Lakeflow) re-derives the HEDIS care gaps
# MAGIC from these raw files, so the gaps are encoded implicitly in the claims/labs/fills, not
# MAGIC handed over directly.
# MAGIC
# MAGIC **Reproducible:** single numpy seed. **Evidence:** row counts, prevalence checks, and
# MAGIC open-gap counts are written to `uhc_stars_demo.ops.evidence` and committed as text.

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

dbutils.widgets.dropdown("dev_mode", "false", ["true", "false"], "Dev mode (10k members)")
dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Target catalog")
DEV_MODE = dbutils.widgets.get("dev_mode") == "true"

# The catalog is pre-provisioned for this workspace (we hold ALL_PRIVILEGES on it); the build
# only creates schemas and volumes inside it. Point this at any catalog you own to reproduce.
CATALOG = dbutils.widgets.get("catalog")
RAW_SCHEMA = "bronze"
RAW_VOLUME = "raw_landing"
OPS_SCHEMA = "ops"
EVIDENCE_VOLUME = "evidence"

RAW_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{RAW_VOLUME}"
EVIDENCE_PATH = f"/Volumes/{CATALOG}/{OPS_SCHEMA}/{EVIDENCE_VOLUME}/01_data_generation"

SEED = 42
MEASUREMENT_YEAR = 2026
PRIOR_YEAR = 2025
N_MEMBERS = 10_000 if DEV_MODE else 100_000
CONTRACTS = ["H1234", "H5678", "H9012"]  # three MA contracts so the row filter has something to filter

print(f"dev_mode={DEV_MODE}  members={N_MEMBERS:,}  seed={SEED}  measurement_year={MEASUREMENT_YEAR}")

# COMMAND ----------

# MAGIC %md ## Catalog, schemas, and volumes

# COMMAND ----------

for sch in ["bronze", "silver", "gold", "ops"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{sch}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{RAW_SCHEMA}.{RAW_VOLUME}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{OPS_SCHEMA}.{EVIDENCE_VOLUME}")

dbutils.fs.mkdirs(EVIDENCE_PATH)
print("catalog / schemas / volumes ready")

# COMMAND ----------

# MAGIC %md ## Generate the population
# MAGIC
# MAGIC Senior MA members with realistic condition prevalence. A set of latent propensity
# MAGIC drivers (tenure, digital channel on file, dual-eligibility, distance to provider) is
# MAGIC generated here and used only to shape the prior-year closure *labels*. The drivers are
# MAGIC observable features; the latent probability itself is never emitted, so the model has
# MAGIC honest signal to learn rather than a leaked label.

# COMMAND ----------

import numpy as np
import pandas as pd
from datetime import date, timedelta

rng = np.random.default_rng(SEED)

COUNTIES = [
    "Hennepin", "Ramsey", "Dakota", "Anoka", "Washington", "Olmsted",
    "Maricopa", "Pima", "Travis", "Harris", "Cook", "Franklin",
]

mid = np.arange(1, N_MEMBERS + 1)
member_id = np.array([f"M{n:08d}" for n in mid])
contract_id = rng.choice(CONTRACTS, size=N_MEMBERS, p=[0.5, 0.3, 0.2])
plan_id = np.array([f"{c}-{p:03d}" for c, p in zip(contract_id, rng.integers(1, 4, N_MEMBERS))])

# Ages 65-90, skewed toward the mid-70s
age = np.clip(rng.normal(74, 6, N_MEMBERS).round().astype(int), 65, 90)
today = date(MEASUREMENT_YEAR, 12, 31)  # measurement anchor; used for enrollment start below
# Birth date: randomize month/day within each member's birth year rather than pinning
# everyone to Dec 31. Drawn from a dedicated RNG so the main stream (and every downstream
# count: prevalence, open gaps, labels) is byte-for-byte unchanged. Age stays the integer
# source of truth; any day in birth_year is still before the Dec-31 measurement date, so
# age derived from birth_date as of year-end matches `age` exactly.
bd_rng = np.random.default_rng(SEED + 1)
birth_doy = bd_rng.integers(0, 365, N_MEMBERS)
birth_date = np.array([date(MEASUREMENT_YEAR - int(a), 1, 1) + timedelta(days=int(d))
                       for a, d in zip(age, birth_doy)])
sex = rng.choice(["F", "M"], size=N_MEMBERS, p=[0.55, 0.45])
county = rng.choice(COUNTIES, size=N_MEMBERS)
dual_eligible = rng.random(N_MEMBERS) < 0.20
tenure_months = np.clip(rng.gamma(3.0, 14.0, N_MEMBERS).round().astype(int), 1, 180)
enroll_start = np.array([today - timedelta(days=int(m) * 30) for m in tenure_months])
digital_channel = rng.random(N_MEMBERS) < 0.55  # email/app on file

roster = pd.DataFrame({
    "member_id": member_id,
    "contract_id": contract_id,
    "plan_id": plan_id,
    "birth_date": birth_date,
    "sex": sex,
    "county": county,
    "dual_eligible": dual_eligible,
    "enroll_start": enroll_start,
    "tenure_months": tenure_months,
    "digital_channel_on_file": digital_channel,  # operational attribute beyond the core key columns
})
print(f"roster rows: {len(roster):,}")

# COMMAND ----------

# MAGIC %md ## Conditions
# MAGIC
# MAGIC Diabetes ~25%, hypertension higher (~62%), both rising mildly with age. Conditions
# MAGIC decide which HEDIS measures apply to each member.

# COMMAND ----------

age_lift = (age - 65) / 25.0  # 0 at 65, 1 at 90
diabetes = rng.random(N_MEMBERS) < (0.25 + 0.05 * age_lift)
hypertension = rng.random(N_MEMBERS) < (0.62 + 0.08 * age_lift)
on_diabetes_meds = diabetes & (rng.random(N_MEMBERS) < 0.85)  # some are diet-controlled
col_eligible = age < 76  # COL screening age window

print(f"diabetes: {diabetes.mean():.1%}   hypertension: {hypertension.mean():.1%}   "
      f"diabetics on meds: {on_diabetes_meds.mean():.1%}   COL-eligible: {col_eligible.mean():.1%}")

# COMMAND ----------

# MAGIC %md ## Latent closure propensity
# MAGIC
# MAGIC A per-member latent probability that outreach closes a gap, driven by observable
# MAGIC features. Used only to sample prior-year outcomes (the training labels). Never emitted.

# COMMAND ----------

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))

# distance proxy: most members see a provider in their own county (near); some are cross-county (far)
far_from_provider = rng.random(N_MEMBERS) < 0.30
distance_miles = np.where(far_from_provider,
                          rng.uniform(25, 60, N_MEMBERS),
                          rng.uniform(1, 15, N_MEMBERS)).round(1)

z = (
    -0.2
    + 0.012 * (tenure_months - 36)        # longer-tenured members engage more
    + 0.9 * digital_channel                # reachable digitally
    - 0.015 * (distance_miles - 10)        # distance hurts
    - 0.3 * dual_eligible                  # dual members harder to reach on average
    + rng.normal(0, 0.4, N_MEMBERS)        # irreducible noise so nothing is deterministic
)
p_close_latent = sigmoid(z)

# distance is a real driver of the latent propensity, so emit it on the roster as an operational
# attribute. Without this the model could not honestly learn the distance signal.
roster["distance_to_provider_miles"] = distance_miles

print(f"latent p_close  mean={p_close_latent.mean():.3f}  "
      f"p10={np.percentile(p_close_latent,10):.3f}  p90={np.percentile(p_close_latent,90):.3f}")

# COMMAND ----------

# MAGIC %md ## Current-year compliance
# MAGIC
# MAGIC For each applicable measure, decide whether the member is already compliant this year.
# MAGIC Non-compliant members are the open gaps Layer 2 will re-derive from the raw files below.

# COMMAND ----------

# baseline compliance rates per measure (fraction already compliant this year)
BASE_COMPLIANCE = {"EED": 0.63, "GSD": 0.78, "CBP": 0.60, "COL": 0.68, "MAD": 0.72}

eed_compliant = diabetes & (rng.random(N_MEMBERS) < BASE_COMPLIANCE["EED"])
gsd_compliant = diabetes & (rng.random(N_MEMBERS) < BASE_COMPLIANCE["GSD"])
cbp_compliant = hypertension & (rng.random(N_MEMBERS) < BASE_COMPLIANCE["CBP"])
col_compliant = col_eligible & (rng.random(N_MEMBERS) < BASE_COMPLIANCE["COL"])
# MAD compliance is realized through pharmacy fills (PDC >= 0.8), decided below
mad_target_adherent = on_diabetes_meds & (rng.random(N_MEMBERS) < BASE_COMPLIANCE["MAD"])

# COMMAND ----------

# MAGIC %md ## Providers

# COMMAND ----------

try:
    from faker import Faker
    fake = Faker()
    Faker.seed(SEED)
    group_name_pool = [fake.company() + " Health" for _ in range(60)]
except Exception:
    group_name_pool = [f"Group {i:02d} Health" for i in range(60)]

N_PROVIDERS = 400 if not DEV_MODE else 80
specialties = rng.choice(
    ["Primary Care", "Ophthalmology", "Endocrinology", "Cardiology", "Gastroenterology"],
    size=N_PROVIDERS, p=[0.45, 0.15, 0.12, 0.14, 0.14])
providers = pd.DataFrame({
    "provider_id": [f"P{n:06d}" for n in range(1, N_PROVIDERS + 1)],
    "npi": rng.integers(1_000_000_000, 1_999_999_999, N_PROVIDERS).astype(str),
    "specialty": specialties,
    "group_name": rng.choice(group_name_pool, N_PROVIDERS),
    "panel_county": rng.choice(COUNTIES, N_PROVIDERS),
})
pcp_ids = providers.loc[providers.specialty == "Primary Care", "provider_id"].to_numpy()
member_pcp = rng.choice(pcp_ids, size=N_MEMBERS)
print(f"providers: {len(providers):,}  ({len(pcp_ids)} PCPs)")

# COMMAND ----------

# MAGIC %md ## Medical claims
# MAGIC
# MAGIC Every member gets routine office visits. Compliance-closing procedures are emitted
# MAGIC only for compliant members, so "no eye-exam CPT this year" genuinely means an open EED
# MAGIC gap when Layer 2 re-derives it.

# COMMAND ----------

def rand_dates(n, year):
    start = date(year, 1, 1)
    return np.array([start + timedelta(days=int(d)) for d in rng.integers(0, 365, n)])

claim_rows = []
cid = 0

def add_claims(mask, cpt, icd, pos, year=MEASUREMENT_YEAR, n_each=1):
    """Append one claim per member in mask (n_each visits)."""
    global cid, claim_rows
    idx = np.where(mask)[0]
    for _ in range(n_each):
        if len(idx) == 0:
            break
        svc = rand_dates(len(idx), year)
        prov = rng.choice(providers.provider_id.to_numpy(), len(idx))
        claim_rows.append(pd.DataFrame({
            "claim_id": [f"C{cid + i:09d}" for i in range(len(idx))],
            "member_id": member_id[idx],
            "service_date": svc,
            "provider_id": prov,
            "place_of_service": pos,
            "cpt_hcpcs": cpt,
            "icd10_dx": icd,
            "claim_status": "paid",
        }))
        cid += len(idx)

# routine office visits for everyone (1-2)
add_claims(np.ones(N_MEMBERS, bool), "99214", "Z00.00", "11", n_each=1)
add_claims(rng.random(N_MEMBERS) < 0.6, "99213", "Z00.00", "11", n_each=1)
# diabetes / hypertension management visits
add_claims(diabetes, "99214", "E11.9", "11")
add_claims(hypertension, "99214", "I10", "11")
# EED: diabetic retinal eye exam only for compliant
add_claims(eed_compliant, "92014", "E11.9", "11")
# COL: screening (colonoscopy or FIT) only for compliant
col_colonoscopy = col_compliant & (rng.random(N_MEMBERS) < 0.4)
add_claims(col_colonoscopy, "45378", "Z12.11", "22")
add_claims(col_compliant & ~col_colonoscopy, "82274", "Z12.11", "81")

medical_claims = pd.concat(claim_rows, ignore_index=True)
medical_claims["service_month"] = pd.to_datetime(medical_claims["service_date"]).dt.strftime("%Y-%m")
print(f"medical_claims rows: {len(medical_claims):,}")

# COMMAND ----------

# MAGIC %md ## Lab results
# MAGIC
# MAGIC HbA1c for diabetics with a GSD-compliant test; blood-pressure readings for hypertensives
# MAGIC (CBP compliant = controlled reading below 140/90).

# COMMAND ----------

lab_rows = []
lid = 0

def add_labs(mask, loinc, test_name, values, year=MEASUREMENT_YEAR):
    global lid, lab_rows
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return
    res = rand_dates(len(idx), year)
    lab_rows.append(pd.DataFrame({
        "lab_id": [f"L{lid + i:09d}" for i in range(len(idx))],
        "member_id": member_id[idx],
        "result_date": res,
        "loinc": loinc,
        "test_name": test_name,
        "result_value": np.asarray(values).astype(str),
    }))
    lid += len(idx)

# GSD: HbA1c test present for compliant diabetics
gsd_idx = np.where(gsd_compliant)[0]
a1c_values = np.round(rng.normal(7.2, 1.3, len(gsd_idx)), 1)
add_labs(gsd_compliant, "4548-4", "Hemoglobin A1c", a1c_values)

# CBP: BP readings for hypertensives; compliant => controlled (<140/90), else elevated
htn_idx = np.where(hypertension)[0]
systolic = np.where(cbp_compliant[htn_idx],
                    rng.integers(118, 139, len(htn_idx)),
                    rng.integers(141, 170, len(htn_idx)))
diastolic = np.where(cbp_compliant[htn_idx],
                     rng.integers(70, 89, len(htn_idx)),
                     rng.integers(91, 104, len(htn_idx)))
add_labs(hypertension, "8480-6", "Systolic Blood Pressure", systolic)
add_labs(hypertension, "8462-4", "Diastolic Blood Pressure", diastolic)

lab_results = pd.concat(lab_rows, ignore_index=True)
print(f"lab_results rows: {len(lab_results):,}")

# COMMAND ----------

# MAGIC %md ## Pharmacy fills
# MAGIC
# MAGIC Diabetes medication fills across the year. PDC (proportion of days covered) is realized
# MAGIC through fill cadence: adherent members fill consistently (PDC >= 0.8), non-adherent miss
# MAGIC refills. Layer 2 recomputes PDC from these fills and flags the MAD gap at < 0.8.

# COMMAND ----------

fill_rows = []
rxid = 0
med_idx = np.where(on_diabetes_meds)[0]
for i in med_idx:
    # target PDC: adherent members high, non-adherent low
    if mad_target_adherent[i]:
        pdc_target = rng.uniform(0.80, 0.98)
    else:
        pdc_target = rng.uniform(0.30, 0.78)
    n_fills = max(1, int(round(pdc_target * 12)))  # 30-day fills across the year
    months = np.sort(rng.choice(np.arange(12), size=min(n_fills, 12), replace=False))
    for refill, m in enumerate(months):
        fill_rows.append((
            f"RX{rxid:09d}", member_id[i],
            date(MEASUREMENT_YEAR, int(m) + 1, min(1 + int(rng.integers(0, 27)), 28)),
            f"00093-{rng.integers(1000,9999)}-{rng.integers(10,99)}",
            "Oral Antidiabetics", 30, refill,
        ))
        rxid += 1

pharmacy_fills = pd.DataFrame(fill_rows, columns=[
    "rx_id", "member_id", "fill_date", "ndc", "drug_class", "days_supply", "refill_number"])
pharmacy_fills["fill_month"] = pd.to_datetime(pharmacy_fills["fill_date"]).dt.strftime("%Y-%m")
print(f"pharmacy_fills rows: {len(pharmacy_fills):,}")

# COMMAND ----------

# MAGIC %md ## Prior-year outreach history (training labels)
# MAGIC
# MAGIC Last year's outreach outcomes. For a sample of members who had an open gap in the prior
# MAGIC year, we draw an outcome from the latent propensity. `outcome == closed` is the training
# MAGIC label the propensity model learns. This is the honest train-on-the-past design: the model
# MAGIC never sees the current-year gaps it will score.

# COMMAND ----------

MEASURES = ["EED", "GSD", "CBP", "COL", "MAD"]
MEASURE_APPLIES = {
    "EED": diabetes, "GSD": diabetes, "MAD": on_diabetes_meds,
    "CBP": hypertension, "COL": col_eligible,
}
CHANNELS = ["phone", "sms", "email", "mail"]
coordinator_ids = [f"CO{n:03d}" for n in range(1, 21)]

oh_rows = []
oid = 0
for measure in MEASURES:
    applies = MEASURE_APPLIES[measure]
    # prior-year members who were outreached for an open gap (sample of those the measure applies to)
    outreached = applies & (rng.random(N_MEMBERS) < 0.45)
    idx = np.where(outreached)[0]
    if len(idx) == 0:
        continue
    p = p_close_latent[idx]
    # a mild measure effect: adherence (MAD) slightly harder to close via a single touch
    p = np.clip(p * (0.9 if measure == "MAD" else 1.0), 0.01, 0.99)
    closed = rng.random(len(idx)) < p
    r = rng.random(len(idx))
    outcome = np.where(closed, "closed",
              np.where(r < 0.5, "no_response",
              np.where(r < 0.8, "declined", "unreachable")))
    ts = rand_dates(len(idx), PRIOR_YEAR)
    oh_rows.append(pd.DataFrame({
        "outreach_id": [f"OH{oid + k:09d}" for k in range(len(idx))],
        "member_id": member_id[idx],
        "measure_id": measure,
        "channel": rng.choice(CHANNELS, len(idx)),
        "attempt_ts": ts,
        "outcome": outcome,
        "coordinator_id": rng.choice(coordinator_ids, len(idx)),
        "next_action": np.where(closed, "none", "retry"),
    }))
    oid += len(idx)

outreach_history = pd.concat(oh_rows, ignore_index=True)
print(f"outreach_history rows: {len(outreach_history):,}  "
      f"closure rate: {(outreach_history.outcome == 'closed').mean():.1%}")

# COMMAND ----------

# MAGIC %md ## Write raw files to the volume
# MAGIC
# MAGIC Batch tables (roster, providers, labs, outreach history) land as single CSV folders.
# MAGIC Claims and pharmacy fills land partitioned by service month so Layer 2's Auto Loader
# MAGIC ingests them as streaming/append tables (the freshness story).

# COMMAND ----------

def write_batch(pdf, name):
    (spark.createDataFrame(pdf).coalesce(1)
        .write.mode("overwrite").option("header", "true")
        .csv(f"{RAW_PATH}/{name}"))
    print(f"wrote {name}: {len(pdf):,} rows")

def write_monthly(pdf, name, month_col):
    for mval, chunk in pdf.groupby(month_col):
        out = chunk.drop(columns=[month_col])
        (spark.createDataFrame(out).coalesce(1)
            .write.mode("overwrite").option("header", "true")
            .csv(f"{RAW_PATH}/{name}/month={mval}"))
    print(f"wrote {name}: {len(pdf):,} rows across {pdf[month_col].nunique()} monthly files")

write_batch(roster, "member_roster")
write_batch(providers, "providers")
write_batch(lab_results, "lab_results")
write_batch(outreach_history, "outreach_history")
write_monthly(medical_claims, "medical_claims", "service_month")
write_monthly(pharmacy_fills, "pharmacy_fills", "fill_month")

# COMMAND ----------

# MAGIC %md ## Run evidence (committed as text)
# MAGIC
# MAGIC Row counts, prevalence checks, and the intended open-gap counts per measure. Layer 2
# MAGIC re-derives gaps independently; these counts are the target it should reproduce.

# COMMAND ----------

import json

# intended open gaps this year (non-compliant among applicable)
intended_open = {
    "EED": int((diabetes & ~eed_compliant).sum()),
    "GSD": int((diabetes & ~gsd_compliant).sum()),
    "CBP": int((hypertension & ~cbp_compliant).sum()),
    "COL": int((col_eligible & ~col_compliant).sum()),
    "MAD": int((on_diabetes_meds & ~mad_target_adherent).sum()),
}

row_counts = {
    "member_roster": len(roster),
    "providers": len(providers),
    "medical_claims": len(medical_claims),
    "pharmacy_fills": len(pharmacy_fills),
    "lab_results": len(lab_results),
    "outreach_history": len(outreach_history),
}

summary = {
    "dev_mode": DEV_MODE,
    "seed": SEED,
    "n_members": int(N_MEMBERS),
    "measurement_year": MEASUREMENT_YEAR,
    "prior_year": PRIOR_YEAR,
    "row_counts": row_counts,
    "prevalence": {
        "diabetes": round(float(diabetes.mean()), 4),
        "hypertension": round(float(hypertension.mean()), 4),
        "diabetics_on_meds": round(float(on_diabetes_meds.mean()), 4),
        "dual_eligible": round(float(dual_eligible.mean()), 4),
    },
    "intended_open_gaps": intended_open,
    "intended_open_gaps_total": int(sum(intended_open.values())),
    "prior_year_outreach_closure_rate": round(float((outreach_history.outcome == "closed").mean()), 4),
}

# markdown evidence
lines = [
    "# Layer 1 evidence: synthetic data generation", "",
    f"- dev_mode: `{DEV_MODE}`  |  seed: `{SEED}`  |  members: `{N_MEMBERS:,}`  |  "
    f"measurement year: `{MEASUREMENT_YEAR}`", "",
    "## Row counts (raw files landed)", "",
    "| Table | Rows |", "| --- | --- |",
]
for k, v in row_counts.items():
    lines.append(f"| {k} | {v:,} |")
lines += [
    "", "## Prevalence checks", "",
    "| Attribute | Rate |", "| --- | --- |",
    f"| diabetes | {diabetes.mean():.1%} |",
    f"| hypertension | {hypertension.mean():.1%} |",
    f"| diabetics on meds | {on_diabetes_meds.mean():.1%} |",
    f"| dual eligible | {dual_eligible.mean():.1%} |",
    "", "## Intended open gaps this year (Layer 2 target)", "",
    "| Measure | Open gaps |", "| --- | --- |",
]
for k, v in intended_open.items():
    lines.append(f"| {k} | {v:,} |")
lines += [
    f"| **total** | **{sum(intended_open.values()):,}** |", "",
    f"Prior-year outreach closure rate (training base rate): "
    f"**{(outreach_history.outcome == 'closed').mean():.1%}**", "",
]

dbutils.fs.put(f"{EVIDENCE_PATH}/summary.json", json.dumps(summary, indent=2), overwrite=True)
dbutils.fs.put(f"{EVIDENCE_PATH}/run_evidence.md", "\n".join(lines), overwrite=True)

# sample rows (synthetic, safe to commit)
for name, pdf in [("member_roster", roster), ("medical_claims", medical_claims.drop(columns=["service_month"])),
                  ("pharmacy_fills", pharmacy_fills.drop(columns=["fill_month"])),
                  ("lab_results", lab_results), ("providers", providers),
                  ("outreach_history", outreach_history)]:
    dbutils.fs.put(f"{EVIDENCE_PATH}/sample_{name}.csv", pdf.head(5).to_csv(index=False), overwrite=True)

print("\n".join(lines))
print(f"\nevidence written to {EVIDENCE_PATH}")
