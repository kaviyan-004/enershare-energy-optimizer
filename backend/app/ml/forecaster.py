"""
AI/ML Forecasting Engine for EnerShare AI.
Implements persistence baseline and XGBoost advanced model.
Prevents target leakage via chronological splitting.
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any
import warnings

# XGBoost
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

# Fallback to sklearn GradientBoosting
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error


def _compute_metrics(actual: np.ndarray, predicted: np.ndarray) -> Dict[str, float]:
    """Compute MAE, RMSE, and MAPE (only when safe)."""
    mae = float(mean_absolute_error(actual, predicted))
    rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
    # MAPE: only when no zero actuals
    nonzero = actual != 0
    if nonzero.sum() > 0:
        mape = float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)
    else:
        mape = None
    return {"mae": mae, "rmse": rmse, "mape": mape}


def _persistence_forecast(series: pd.Series, horizon: int) -> np.ndarray:
    """Seasonal-naive persistence: same hour yesterday."""
    values = series.values
    n = len(values)
    predictions = []
    for i in range(horizon):
        # Use 24 hours back (same hour previous day)
        lag_idx = n - 24 + (i % 24)
        if lag_idx < 0:
            lag_idx = 0
        predictions.append(values[lag_idx])
    return np.array(predictions, dtype=float)


def _build_features(df: pd.DataFrame, target_col: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Feature engineering for time-series forecasting.
    Returns feature DataFrame and list of feature names.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    features = pd.DataFrame(index=df.index)

    # Calendar features
    features["hour"] = df["timestamp"].dt.hour
    features["hour_sin"] = np.sin(2 * np.pi * features["hour"] / 24)
    features["hour_cos"] = np.cos(2 * np.pi * features["hour"] / 24)
    features["day_of_week"] = df["timestamp"].dt.dayofweek
    features["day_sin"] = np.sin(2 * np.pi * features["day_of_week"] / 7)
    features["day_cos"] = np.cos(2 * np.pi * features["day_of_week"] / 7)
    features["month"] = df["timestamp"].dt.month
    features["month_sin"] = np.sin(2 * np.pi * features["month"] / 12)
    features["is_weekend"] = (features["day_of_week"] >= 5).astype(int)

    feature_names = list(features.columns)

    # Lag features (target)
    if target_col in df.columns:
        target = df[target_col].values
        for lag in [1, 2, 3, 6, 12, 24, 48]:
            col = f"lag_{lag}h"
            shifted = pd.Series(target).shift(lag)
            features[col] = shifted.values
            feature_names.append(col)

        # Rolling averages
        for window in [3, 6, 12, 24]:
            col = f"roll_mean_{window}h"
            features[col] = pd.Series(target).shift(1).rolling(window, min_periods=1).mean().values
            feature_names.append(col)

    # Weather features (when available)
    for weather_col in ["irradiance_wm2", "temperature_c", "cloud_cover_pct", "wind_speed_ms"]:
        if weather_col in df.columns and df[weather_col].notna().sum() > 0:
            features[weather_col] = df[weather_col].fillna(df[weather_col].median())
            feature_names.append(weather_col)

    # Tariff feature
    if "import_tariff_inr_kwh" in df.columns:
        features["import_tariff"] = df["import_tariff_inr_kwh"].fillna(8.5)
        feature_names.append("import_tariff")

    return features, feature_names


class EnerShareForecaster:
    """
    Unified forecasting engine for generation and demand.
    Supports persistence baseline and XGBoost (or sklearn GB fallback).
    """

    def __init__(self, target: str = "solar_kwh", model_name: str = "xgboost"):
        self.target = target
        self.model_name = model_name
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []
        self.is_fitted = False
        self.warnings: List[str] = []

        # Resolve effective model
        if model_name == "xgboost" and not XGBOOST_AVAILABLE:
            self.effective_model_name = "gradient_boost"
            self.warnings.append(
                "XGBoost not available; using sklearn GradientBoostingRegressor as fallback."
            )
        else:
            self.effective_model_name = model_name

    def _build_model(self):
        if self.effective_model_name == "xgboost":
            return xgb.XGBRegressor(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=3,
                random_state=42,
                n_jobs=1,
            )
        else:
            return GradientBoostingRegressor(
                n_estimators=150,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
            )

    def fit(
        self, df: pd.DataFrame, val_fraction: float = 0.15
    ) -> Dict[str, Any]:
        """
        Train the model using chronological train/validation split.
        Returns evaluation metrics.
        """
        self.warnings = []
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        if self.target not in df.columns:
            raise ValueError(f"Target column '{self.target}' not found in dataset.")

        n = len(df)
        if n < 72:
            self.warnings.append(
                f"Only {n} records available. Minimum 72 recommended for reliable training."
            )

        # Chronological split — no shuffling, no leakage
        val_size = max(24, int(n * val_fraction))
        train_end = n - val_size

        if train_end < 48:
            self.warnings.append("Insufficient training data. Using persistence baseline only.")
            self.is_fitted = False
            return {"status": "insufficient_data", "warnings": self.warnings}

        features, feature_names = _build_features(df, self.target)
        self.feature_names = feature_names

        target_values = df[self.target].values.astype(float)

        # Drop rows with NaN features (from lag/rolling at start)
        valid_mask = ~pd.DataFrame(features[feature_names]).isna().any(axis=1).values
        valid_mask[:48] = False  # Warmup window for lags

        X_all = features[feature_names].values
        y_all = target_values

        X_train = X_all[valid_mask & (np.arange(n) < train_end)]
        y_train = y_all[valid_mask & (np.arange(n) < train_end)]
        X_val = X_all[valid_mask & (np.arange(n) >= train_end)]
        y_val = y_all[valid_mask & (np.arange(n) >= train_end)]

        if len(X_train) < 24 or len(X_val) < 1:
            self.warnings.append("Not enough clean samples after lag warmup.")
            self.is_fitted = False
            return {"status": "insufficient_samples", "warnings": self.warnings}

        # Persistence baseline evaluation
        persistence_val = []
        for i, idx in enumerate(np.where(valid_mask & (np.arange(n) >= train_end))[0]):
            lag_idx = idx - 24
            if lag_idx >= 0:
                persistence_val.append(y_all[lag_idx])
            else:
                persistence_val.append(y_all[0])
        persistence_val = np.array(persistence_val)

        baseline_metrics = _compute_metrics(y_val, persistence_val)

        # Advanced model
        self.model = self._build_model()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(X_train, y_train)

        val_pred = np.maximum(0, self.model.predict(X_val))
        val_metrics = _compute_metrics(y_val, val_pred)

        self.is_fitted = True

        return {
            "status": "trained",
            "model": self.effective_model_name,
            "train_samples": int(len(X_train)),
            "val_samples": int(len(X_val)),
            "val_mae": val_metrics["mae"],
            "val_rmse": val_metrics["rmse"],
            "val_mape": val_metrics["mape"],
            "baseline_mae": baseline_metrics["mae"],
            "baseline_rmse": baseline_metrics["rmse"],
            "feature_count": len(feature_names),
            "warnings": self.warnings,
        }

    def predict(
        self, df: pd.DataFrame, horizon: int = 24
    ) -> Tuple[List[float], List[str]]:
        """
        Generate predictions for the next `horizon` intervals.
        Uses trained model if available; falls back to persistence baseline.
        Returns (predictions_list, warnings_list).
        """
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        target = df[self.target].values if self.target in df.columns else None
        predictions = []
        warn = list(self.warnings)

        if not self.is_fitted or self.model is None:
            warn.append("Model not trained; using persistence baseline.")
            series = pd.Series(target if target is not None else np.zeros(24))
            preds = _persistence_forecast(series, horizon)
            return list(np.maximum(0.0, preds)), warn

        features, _ = _build_features(df, self.target)

        # Predict on last known rows and extrapolate horizon
        # We use the last rows of the dataset to predict for the forecast horizon
        n = len(df)
        pred_indices = list(range(max(0, n - horizon), n))

        if len(pred_indices) < horizon:
            warn.append(f"Not enough history for full {horizon}-hour horizon; padding with last known.")

        available_features = [f for f in self.feature_names if f in features.columns]
        missing = [f for f in self.feature_names if f not in features.columns]
        if missing:
            warn.append(f"Missing features: {missing[:5]}. Using available subset.")

        X_pred = features[available_features].iloc[pred_indices].values

        # Fill NaN in prediction features with column means
        col_means = np.nanmean(X_pred, axis=0)
        nan_mask = np.isnan(X_pred)
        inds = np.where(nan_mask)
        X_pred[inds] = np.take(col_means, inds[1])

        raw_preds = self.model.predict(X_pred)
        predictions = list(np.maximum(0.0, raw_preds).tolist())

        # Pad or trim to horizon
        while len(predictions) < horizon:
            predictions.append(predictions[-1] if predictions else 0.0)
        predictions = predictions[:horizon]

        return predictions, warn

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "requested_model": self.model_name,
            "effective_model": self.effective_model_name,
            "xgboost_available": XGBOOST_AVAILABLE,
            "is_fitted": self.is_fitted,
            "feature_count": len(self.feature_names),
            "warnings": self.warnings,
        }
