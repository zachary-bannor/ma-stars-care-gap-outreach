# Layer 4 / ML propensity: run evidence

Gradient-boosted model (XGBoost) for P(member closes an open gap | contacted),
isotonic-calibrated, MLflow-tracked, registered to Unity Catalog as
`zrb_fe_bar_uhc_stars_catalog.gold.gap_closure_propensity` @champion (version 2), and
batch-scored to `gold.gap_scores`.

## Honesty of the signal

The label is last year's outreach `outcome == 'closed'`. Layer 1 drew those
outcomes from a latent per-member propensity that is **never written to any
table**, so the model cannot read it. It recovers the signal from observable
features. The prior-closure-rate feature is built leave-one-out (a row's own
outcome is removed from its own feature) and the split is by member, so no
outcome leaks into training or across the test boundary.

The recovered-not-cheated proof is the feature importance below: tenure, digital
channel, distance, dual status, and the prior-closure-rate proxy carry the
signal, exactly the drivers Layer 1 used; age and the condition flags, which
Layer 1 never tied to closure, come back near zero.

## Held-out test metrics (fully held-out, split by member)

| metric | value |
| --- | --- |
| ROC-AUC | 0.6489 |
| PR-AUC | 0.6613 |
| log loss | 0.6568 |
| Brier (raw) | 0.2317 |
| Brier (calibrated) | 0.2320 |
| base rate | 0.5393 |
| train / val / test rows | 53,996 / 18,072 / 18,182 |

ROC-AUC in the mid-0.6s is the honest ceiling here, not a weak model. Layer 1
draws each prior-year outcome as a Bernoulli trial from the latent propensity, so
the labels carry irreducible noise that no model can separate; a propensity model
that scored much higher would be reading something it should not. The model
instead recovered the true drivers (feature importance below), which is what a
leakage-free fit looks like.

The raw gradient-boosted scores are already well-calibrated (Brier
0.2317); isotonic calibration holds Brier at
0.2320 and the reliability bins below track the
diagonal, so the expected-value ranking multiplies a probability that means what
it says.

## Feature importance

| feature | gain | permutation_importance |
| --- | --- | --- |
| digital_channel_on_file | 0.6765 | 0.0843 |
| tenure_months | 0.0438 | 0.0276 |
| distance_to_provider_miles | 0.0411 | 0.0232 |
| dual_eligible | 0.0502 | 0.0039 |
| prior_closure_rate_smoothed | 0.0284 | 0.0028 |
| measure_MAD | 0.0355 | 0.0016 |
| measure_EED | 0.0132 | 1.0E-4 |
| measure_CBP | 0.0166 | 0.0 |
| is_diabetic | 0.0153 | 0.0 |
| measure_COL | 0.0124 | -1.0E-4 |
| measure_GSD | 0.0157 | -2.0E-4 |
| prior_attempts | 0.0179 | -3.0E-4 |
| is_hypertensive | 0.0158 | -3.0E-4 |
| age | 0.0176 | -4.0E-4 |

## Calibration (test, decile bins)

Predicted probability vs observed closure fraction per decile. Close agreement =
well-calibrated.

| bin | mean_pred | frac_pos | n |
| --- | --- | --- | --- |
| 0 | 0.2773 | 0.3127 | 1829 |
| 1 | 0.3855 | 0.394 | 1840 |
| 2 | 0.4301 | 0.4501 | 2704 |
| 3 | 0.5045 | 0.4939 | 1634 |
| 4 | 0.5492 | 0.5371 | 1536 |
| 5 | 0.5862 | 0.5931 | 1863 |
| 6 | 0.6278 | 0.6195 | 2560 |
| 7 | 0.6595 | 0.675 | 797 |
| 8 | 0.6887 | 0.6705 | 1894 |
| 9 | 0.7473 | 0.7613 | 1525 |

## Scored output: gold.gap_scores

67,202 open gaps scored, mean propensity
0.5360. One row per member x open measure, with the
calibrated propensity and expected Star-weighted value (propensity x Star weight,
MAD triple-weighted). Per measure:

| measure_id | gaps | avg_propensity | avg_expected_value |
| --- | --- | --- | --- |
| CBP | 25,874 | 0.5387 | 0.5387 |
| COL | 19,313 | 0.5391 | 0.5391 |
| EED | 9,827 | 0.543 | 0.543 |
| GSD | 5,835 | 0.5467 | 0.5467 |
| MAD | 6,353 | 0.4951 | 1.4854 |

The top of the worklist (highest expected Star-weighted value) is in
`sample_gap_scores.csv`. The table lives in the engineer-owned gold schema, so it
inherits the Layer 3 posture: business personas have no direct access and consume
it downstream (Lakebase worklist, Genie).
