"""
forecast_model.py

Drop-in version using the teammate's model, but exporting the SAME dashboard files
as the previous forecasting script.

Outputs:
- outputs/forecast_dashboard_long.csv
- outputs/forecast_dashboard_long.json
- outputs/dashboard_crime_predictions.csv
- outputs/test_predictions_dashboard.csv
- outputs/model_evaluation_70_30.csv
- outputs/model_metadata.json
- outputs/xgb_split_model_top5.json
- outputs/xgb_split_model_others.json
- outputs/xgb_tier_T1.json, xgb_tier_T2.json, xgb_tier_T3.json

Run:
python forecast_model.py --data-dir test_data --output-dir outputs --forecast-months 12
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import OneHotEncoder

REQUIRED_COLUMNS = {"Month", "LSOA code", "Crime type"}


def add_months(month_str: str, months: int) -> str:
    year = int(month_str[:4])
    month = int(month_str[5:])
    month_index = year * 12 + (month - 1) + months
    return f"{month_index // 12}-{month_index % 12 + 1:02d}"


class CrimePredictionModel:
    """Teammate 3-tier ensemble: 70% XGBoost + 30% Random Forest."""

    def __init__(self):
        self._reset_state()

    def _reset_state(self):
        self.is_trained = False
        self.period_start = None
        self.period_end = None
        self.last_data_month = None
        self.base_month_dt = None
        self.models = {"xgb": {}, "rf": {}}
        self.bias_factors = {"xgb": {}, "rf": {}}
        self.tiers = {}
        self.ohe = None
        self.unique_lsoas = []
        self.unique_crimes = []
        self.lsoa_cat_dtype = None
        self.crime_cat_dtype = None
        self.bias_month_count = None

    def trainAndBias(self, df: pd.DataFrame):
        self._reset_state()
        if not REQUIRED_COLUMNS.issubset(df.columns):
            raise ValueError(f"Input DataFrame is missing required columns. Need at least: {REQUIRED_COLUMNS}")

        raw_agg = df.groupby(["Month", "LSOA code", "Crime type"]).size().reset_index(name="Number of occurrences")
        all_months = sorted(raw_agg["Month"].unique().tolist())
        self.unique_lsoas = sorted(raw_agg["LSOA code"].dropna().unique().tolist())
        self.unique_crimes = sorted(raw_agg["Crime type"].dropna().unique().tolist())

        if len(all_months) < 3:
            raise ValueError(f"Insufficient data: needs at least 3 months. Found {len(all_months)}.")

        full_idx = pd.MultiIndex.from_product(
            [all_months, self.unique_lsoas, self.unique_crimes],
            names=["Month", "LSOA code", "Crime type"],
        )
        full_df = pd.DataFrame(index=full_idx).reset_index()
        agg_df = full_df.merge(raw_agg, on=["Month", "LSOA code", "Crime type"], how="left")
        agg_df["Number of occurrences"] = agg_df["Number of occurrences"].fillna(0)

        self.period_start = all_months[0]
        self.period_end = all_months[-1]
        self.last_data_month = self.period_end
        self.base_month_dt = datetime.strptime(self.period_start, "%Y-%m")
        self.lsoa_cat_dtype = pd.CategoricalDtype(categories=self.unique_lsoas)
        self.crime_cat_dtype = pd.CategoricalDtype(categories=self.unique_crimes)

        agg_df = self._add_time_features(agg_df)

        # Original teammate model used last 6 months as bias buffer.
        # This version automatically shrinks the buffer if your dataset is small.
        if len(all_months) >= 30:
            bias_n = 6
        else:
            bias_n = max(1, min(3, len(all_months) // 4))
        if len(all_months) - bias_n < 2:
            bias_n = 1
        self.bias_month_count = bias_n

        train_months = all_months[:-bias_n]
        bias_months = all_months[-bias_n:]
        df_train = agg_df[agg_df["Month"].isin(train_months)].copy()
        df_bias = agg_df[agg_df["Month"].isin(bias_months)].copy()

        self.ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(agg_df[["LSOA code", "Crime type"]])

        lsoa_vol = df_train.groupby("LSOA code")["Number of occurrences"].sum().sort_values(ascending=False)
        self.tiers["T1"] = lsoa_vol.index[:1].tolist()
        self.tiers["T2"] = lsoa_vol.index[1:6].tolist()
        self.tiers["T3"] = lsoa_vol.index[6:].tolist()

        for tier_name in ["T1", "T2", "T3"]:
            tier_lsoas = self.tiers[tier_name]
            if not tier_lsoas:
                continue
            tr = df_train[df_train["LSOA code"].isin(tier_lsoas)].copy()
            bi = df_bias[df_bias["LSOA code"].isin(tier_lsoas)].copy()
            if tr.empty:
                continue

            xgb_model = xgb.XGBRegressor(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                objective="count:poisson",
                enable_categorical=True,
                tree_method="hist",
                verbosity=0,
                random_state=42,
            )
            xgb_model.fit(self._xgb_X(tr), tr["Number of occurrences"])
            self.models["xgb"][tier_name] = xgb_model

            rf_model = RandomForestRegressor(
                n_estimators=150,
                max_depth=10,
                min_samples_leaf=3,
                n_jobs=-1,
                random_state=42,
            )
            rf_model.fit(self._rf_X(tr), tr["Number of occurrences"])
            self.models["rf"][tier_name] = rf_model

            if not bi.empty:
                self.bias_factors["xgb"][tier_name] = self._calc_bias(
                    xgb_model.predict(self._xgb_X(bi)), bi["Number of occurrences"]
                )
                self.bias_factors["rf"][tier_name] = self._calc_bias(
                    rf_model.predict(self._rf_X(bi)), bi["Number of occurrences"]
                )
            else:
                self.bias_factors["xgb"][tier_name] = 0.0
                self.bias_factors["rf"][tier_name] = 0.0

        self.is_trained = True
        print(f"Model trained on {len(train_months)} months with {bias_n} bias month(s)")

    def predict_month(self, month_str: str) -> pd.DataFrame:
        if not self.is_trained:
            raise RuntimeError("Cannot predict: model is not trained yet.")

        df_pred = pd.DataFrame(product(self.unique_lsoas, self.unique_crimes), columns=["LSOA code", "Crime type"])
        df_pred["Month"] = month_str
        df_pred = self._add_time_features(df_pred)

        xgb_all = np.zeros(len(df_pred))
        rf_all = np.zeros(len(df_pred))

        for tier_name, tier_lsoas in self.tiers.items():
            idx = df_pred[df_pred["LSOA code"].isin(tier_lsoas)].index
            if len(idx) == 0 or tier_name not in self.models["xgb"]:
                continue
            tg = df_pred.loc[idx].copy()
            xgb_p = self._apply_correction(
                self.models["xgb"][tier_name].predict(self._xgb_X(tg)),
                self.bias_factors["xgb"].get(tier_name, 0.0),
            ).clip(min=0)
            rf_p = self._apply_correction(
                self.models["rf"][tier_name].predict(self._rf_X(tg)),
                self.bias_factors["rf"].get(tier_name, 0.0),
            ).clip(min=0)
            xgb_all[idx] = xgb_p
            rf_all[idx] = rf_p

        df_pred["XGB_Prediction"] = xgb_all
        df_pred["RF_Prediction"] = rf_all
        df_pred["Ensemble_7030_Prediction"] = (0.7 * xgb_all + 0.3 * rf_all).clip(min=0)
        return df_pred[["Month", "LSOA code", "Crime type", "XGB_Prediction", "RF_Prediction", "Ensemble_7030_Prediction"]]

    def predict_horizon(self, forecast_months: int = 12) -> pd.DataFrame:
        months = [add_months(self.last_data_month, i) for i in range(1, forecast_months + 1)]
        return pd.concat([self.predict_month(m) for m in months], ignore_index=True)

    def save_xgb_models(self, output_dir: Path):
        for tier_name, model in self.models["xgb"].items():
            model.save_model(output_dir / f"xgb_tier_{tier_name}.json")
        # Compatibility names from the previous script.
        if "T2" in self.models["xgb"]:
            self.models["xgb"]["T2"].save_model(output_dir / "xgb_split_model_top5.json")
        elif "T1" in self.models["xgb"]:
            self.models["xgb"]["T1"].save_model(output_dir / "xgb_split_model_top5.json")
        if "T3" in self.models["xgb"]:
            self.models["xgb"]["T3"].save_model(output_dir / "xgb_split_model_others.json")

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        dates = pd.to_datetime(df["Month"])
        df["Month_Num"] = dates.dt.month
        df["Time_Index"] = (dates.dt.year - self.base_month_dt.year) * 12 + (dates.dt.month - self.base_month_dt.month)
        return df

    def _xgb_X(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[["Time_Index", "Month_Num", "LSOA code", "Crime type"]].copy()
        X["LSOA code"] = X["LSOA code"].astype(self.lsoa_cat_dtype)
        X["Crime type"] = X["Crime type"].astype(self.crime_cat_dtype)
        return X

    def _rf_X(self, df: pd.DataFrame) -> np.ndarray:
        return np.hstack([df[["Time_Index", "Month_Num"]].values, self.ohe.transform(df[["LSOA code", "Crime type"]])])

    @staticmethod
    def _calc_bias(preds_arr, actual_series):
        total = actual_series.sum()
        return float((preds_arr.sum() - total) / total) if total > 0 else 0.0

    @staticmethod
    def _apply_correction(preds_arr, factor):
        return preds_arr * (1.0 / (1.0 + factor)) if abs(factor) > 1e-9 else preds_arr


def infer_month_from_path(file_path: Path) -> Optional[str]:
    import re
    for candidate in [file_path.stem, file_path.parent.name]:
        match = re.search(r"(20\d{2})[-_](0[1-9]|1[0-2])", candidate)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return None


def find_monthly_csvs(data_dir: Path) -> List[Path]:
    return sorted([p for p in data_dir.glob("**/*.csv") if infer_month_from_path(p) is not None])


def load_raw_crime_data(data_dir: Path) -> pd.DataFrame:
    csvs = find_monthly_csvs(data_dir)
    if not csvs:
        raise FileNotFoundError(f"No monthly crime CSV files found inside {data_dir.resolve()}")
    frames, skipped = [], []
    for csv_path in csvs:
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception as exc:
            skipped.append((str(csv_path), f"read error: {exc}"))
            continue
        month = infer_month_from_path(csv_path)
        if "Month" not in df.columns:
            df["Month"] = month
        if not REQUIRED_COLUMNS.issubset(df.columns):
            skipped.append((str(csv_path), "missing required columns"))
            continue
        df = df[["Month", "LSOA code", "Crime type"]].dropna().copy()
        frames.append(df)
    for path, reason in skipped[:10]:
        print(f"Skipping {path}: {reason}")
    if not frames:
        raise ValueError("No valid crime CSV files found. Required columns: Month, LSOA code, Crime type.")
    return pd.concat(frames, ignore_index=True)


def dashboard_format(preds: pd.DataFrame, prediction_type: str, actual_col="actual_crimes") -> pd.DataFrame:
    out = preds.rename(columns={"Ensemble_7030_Prediction": "predicted_crimes"}).copy()
    if actual_col not in out.columns:
        out["actual_crimes"] = None
    out["prediction_type"] = prediction_type
    out["predicted_crimes"] = out["predicted_crimes"].round().clip(lower=0).astype(int)
    return out[["Month", "LSOA code", "Crime type", "actual_crimes", "predicted_crimes", "prediction_type"]]


def actual_grid(raw_df: pd.DataFrame, months: List[str], lsoas: List[str], crimes: List[str]) -> pd.DataFrame:
    actual = raw_df.groupby(["Month", "LSOA code", "Crime type"]).size().reset_index(name="actual_crimes")
    idx = pd.MultiIndex.from_product([months, lsoas, crimes], names=["Month", "LSOA code", "Crime type"])
    grid = pd.DataFrame(index=idx).reset_index()
    return grid.merge(actual, on=["Month", "LSOA code", "Crime type"], how="left").fillna({"actual_crimes": 0})


def chronological_train_test(raw_df: pd.DataFrame, train_ratio: float = 0.7):
    months = sorted(raw_df["Month"].unique())
    split_idx = max(2, int(len(months) * train_ratio))
    if split_idx >= len(months):
        split_idx = len(months) - 1
    return months[:split_idx], months[split_idx:]


def evaluate_70_30(raw_df: pd.DataFrame):
    train_months, test_months = chronological_train_test(raw_df, 0.7)
    train_df = raw_df[raw_df["Month"].isin(train_months)].copy()
    test_df = raw_df[raw_df["Month"].isin(test_months)].copy()

    eval_model = CrimePredictionModel()
    eval_model.trainAndBias(train_df)

    preds = pd.concat([eval_model.predict_month(m) for m in test_months], ignore_index=True)
    actuals = actual_grid(test_df, test_months, eval_model.unique_lsoas, eval_model.unique_crimes)
    merged = preds.merge(actuals, on=["Month", "LSOA code", "Crime type"], how="left")
    merged["actual_crimes"] = merged["actual_crimes"].fillna(0).astype(int)

    test_dashboard = dashboard_format(merged, "test_prediction")
    mae = mean_absolute_error(test_dashboard["actual_crimes"], test_dashboard["predicted_crimes"])
    rmse = mean_squared_error(test_dashboard["actual_crimes"], test_dashboard["predicted_crimes"], squared=False)

    evaluation = pd.DataFrame([
        {
            "model": "3-tier Ensemble 70/30",
            "train_months": len(train_months),
            "test_months": len(test_months),
            "train_start": min(train_months),
            "train_end": max(train_months),
            "test_start": min(test_months),
            "test_end": max(test_months),
            "mae": mae,
            "rmse": rmse,
        }
    ])
    return test_dashboard, evaluation, train_months, test_months


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("test_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--forecast-months", type=int, default=12)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading raw crime data...")
    raw_df = load_raw_crime_data(args.data_dir)
    months = sorted(raw_df["Month"].unique())
    print(f"Dataset: {months[0]} to {months[-1]} | {len(months)} months | {len(raw_df):,} raw rows")

    print("Evaluating teammate model with chronological 70/30 split...")
    test_predictions, evaluation, train_months, test_months = evaluate_70_30(raw_df)

    print("Retraining teammate model on full dataset before forecasting...")
    final_model = CrimePredictionModel()
    final_model.trainAndBias(raw_df)

    print(f"Creating {args.forecast_months}-month forecast...")
    raw_forecast = final_model.predict_horizon(args.forecast_months)
    forecast_dashboard = dashboard_format(raw_forecast, "forecast_1_year")

    dashboard_all = pd.concat([test_predictions, forecast_dashboard], ignore_index=True)

    forecast_dashboard.to_csv(args.output_dir / "forecast_dashboard_long.csv", index=False)
    forecast_dashboard.to_json(args.output_dir / "forecast_dashboard_long.json", orient="records", indent=2)
    dashboard_all.to_csv(args.output_dir / "dashboard_crime_predictions.csv", index=False)
    test_predictions.to_csv(args.output_dir / "test_predictions_dashboard.csv", index=False)
    evaluation.to_csv(args.output_dir / "model_evaluation_70_30.csv", index=False)
    final_model.save_xgb_models(args.output_dir)

    metadata = {
        "model": " 3-tier Ensemble 70/30",
        "xgboost_weight": 0.7,
        "random_forest_weight": 0.3,
        "features": ["Time_Index", "Month_Num", "LSOA code", "Crime type"],
        "target": "Number of occurrences",
        "training_period_start": final_model.period_start,
        "training_period_end": final_model.period_end,
        "forecast_months": args.forecast_months,
        "forecast_start": forecast_dashboard["Month"].min(),
        "forecast_end": forecast_dashboard["Month"].max(),
        "lsoa_categories": final_model.unique_lsoas,
        "crime_type_categories": final_model.unique_crimes,
        "tiers": final_model.tiers,
        "bias_factors": final_model.bias_factors,
        "bias_month_count": final_model.bias_month_count,
        "evaluation_split": {
            "method": "chronological_70_30",
            "train_start": min(train_months),
            "train_end": max(train_months),
            "test_start": min(test_months),
            "test_end": max(test_months),
        },
    }
    (args.output_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Done. Saved same dashboard outputs as before:")
    for name in [
        "forecast_dashboard_long.csv",
        "forecast_dashboard_long.json",
        "dashboard_crime_predictions.csv",
        "test_predictions_dashboard.csv",
        "model_evaluation_70_30.csv",
        "model_metadata.json",
        "xgb_split_model_top5.json",
        "xgb_split_model_others.json",
    ]:
        print(f"- {args.output_dir / name}")


if __name__ == "__main__":
    main()
