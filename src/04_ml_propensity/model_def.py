"""The registered model: a gradient-boosted classifier wrapped with isotonic
calibration, logged as an MLflow pyfunc.

gap_scores multiplies this model's output by the measure Star weight to rank
outreach, so the probability has to mean what it says, not just rank correctly.
Raw gradient-boosted scores are often miscalibrated, so the fitted XGBoost model
is paired with an isotonic calibrator fit on a held-out split. This wrapper
applies both in order and returns the calibrated P(close | contacted).

Logged with code_paths so the class definition travels with the model and the
scoring UDF can reconstruct it from the Unity Catalog registry.
"""
import mlflow.pyfunc


class GapPropensityModel(mlflow.pyfunc.PythonModel):
    def __init__(self, clf=None, iso=None, feature_columns=None):
        self.clf = clf
        self.iso = iso
        self.feature_columns = feature_columns

    def predict(self, context, model_input):
        # model_input arrives as a pandas DataFrame (direct call or spark_udf
        # struct). Select the canonical feature order, coerce to float (Spark can
        # hand over decimals as object dtype), score, then calibrate.
        x = model_input[self.feature_columns].astype("float64")
        raw = self.clf.predict_proba(x)[:, 1]
        return self.iso.predict(raw)
