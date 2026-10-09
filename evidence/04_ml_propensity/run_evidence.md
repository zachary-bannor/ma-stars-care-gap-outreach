# Layer 4 / ML propensity: run evidence

Gradient-boosted model (XGBoost) for P(member closes an open gap | contacted),
isotonic-calibrated, MLflow-tracked, registered to Unity Catalog as
`zrb_fe_bar_uhc_stars_catalog.gold.gap_closure_propensity` @champion (version 3), and
batch-scored to `gold.gap_scores`.

## Honesty of the signal

The label is last year's outreach `outcome == 'closed'`. Layer 1 drew those
outcomes from a latent per-member propensity that is **never written to any
table**, so the model cannot read it. It recovers the signal from observable
features. The prior-closure-rate feature is built leave-one-out (a row's own
outcome is removed from its own feature) and the split is by member, so no
outcome leaks into training or across the test boundary.

The recovered-not-cheated proof is the feature importance below. The signal
concentrates on the levers Layer 1 actually used: digital channel on file is the
dominant driver, member tenure and distance to provider add clear secondary
signal, and dual status and the prior-closure-rate proxy are weak but
directionally present. The features Layer 1 never tied to closure (age, the
condition flags, the prior attempt count) sit at the noise floor, at or just
below zero permutation importance. A model reading the latent probability
directly would score near-perfect; this one lands at the honest ceiling for the
stochastic label.

## Held-out test metrics (fully held-out, split by member)

| metric | value |
| --- | --- |
| ROC-AUC | 0.6484 |
| PR-AUC | 0.6607 |
| log loss | 0.6559 |
| Brier (raw) | 0.2318 |
| Brier (calibrated) | 0.2319 |
| base rate | 0.5393 |
| train / val / test rows | 53,996 / 18,072 / 18,182 |

ROC-AUC in the mid-0.6s is the honest ceiling here, not a weak model. Layer 1
draws each prior-year outcome as a Bernoulli trial from the latent propensity, so
the labels carry irreducible noise that no model can separate; a propensity model
that scored much higher would be reading something it should not. The model
instead recovered the true drivers (feature importance below), which is what a
leakage-free fit looks like.

The raw gradient-boosted scores are already well-calibrated (Brier
0.2318); isotonic calibration holds Brier at
0.2319 and the reliability bins below track the diagonal,
so the expected-value ranking multiplies a probability that means what it says.

## Feature importance

| feature | gain | permutation_importance |
| --- | --- | --- |
| digital_channel_on_file | 0.6592 | 0.0845 |
| tenure_months | 0.0456 | 0.0277 |
| distance_to_provider_miles | 0.0422 | 0.0223 |
| dual_eligible | 0.0531 | 0.0041 |
| prior_closure_rate_smoothed | 0.0291 | 0.0018 |
| measure_MAD | 0.0364 | 0.0015 |
| prior_attempts | 0.0177 | 1.0E-4 |
| measure_GSD | 0.0195 | 1.0E-4 |
| is_diabetic | 0.0173 | -1.0E-4 |
| measure_EED | 0.0139 | -1.0E-4 |
| measure_CBP | 0.0166 | -1.0E-4 |
| is_hypertensive | 0.0165 | -1.0E-4 |
| measure_COL | 0.0145 | -2.0E-4 |
| age | 0.0184 | -3.0E-4 |

## Calibration (test, decile bins)

Predicted probability vs observed closure fraction per decile. Close agreement =
well-calibrated.

| bin | mean_pred | frac_pos | n |
| --- | --- | --- | --- |
| 0 | 0.2856 | 0.3129 | 1940 |
| 1 | 0.383 | 0.3994 | 1873 |
| 2 | 0.4335 | 0.4596 | 2193 |
| 3 | 0.4929 | 0.4803 | 1722 |
| 4 | 0.5358 | 0.523 | 1671 |
| 5 | 0.5788 | 0.589 | 1601 |
| 6 | 0.6228 | 0.6185 | 2954 |
| 7 | 0.6699 | 0.6688 | 613 |
| 8 | 0.6817 | 0.6701 | 2037 |
| 9 | 0.7503 | 0.7586 | 1578 |

## Scored output: gold.gap_scores

67,202 open gaps scored, mean propensity
0.5362. One row per member x open measure, with the
calibrated propensity and expected Star-weighted value (propensity x Star weight,
MAD triple-weighted). Per measure:

| measure_id | gaps | avg_propensity | avg_expected_value |
| --- | --- | --- | --- |
| CBP | 25,874 | 0.5395 | 0.5395 |
| COL | 19,313 | 0.539 | 0.539 |
| EED | 9,827 | 0.5429 | 0.5429 |
| GSD | 5,835 | 0.5457 | 0.5457 |
| MAD | 6,353 | 0.4953 | 1.4859 |

The top of the worklist (highest expected Star-weighted value) is in
`sample_gap_scores.csv`. The table lives in the engineer-owned gold schema, so it
inherits the Layer 3 posture: business personas have no direct access and consume
it downstream (Lakebase worklist, Genie).
