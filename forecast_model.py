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
- outputs/xgb_tier_T1.json, xgb_tier_T2.json, xgb_tier_T3.json
- outputs/rf_tier_T1.json, rf_tier_T2.json, rf_tier_T3.json

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
from sklearn.metrics import mean_absolute_error, mean_squared_error

REQUIRED_COLUMNS = {"Month", "LSOA code", "Crime type"}


def add_months(month_str: str, months: int) -> str:
    year = int(month_str[:4])
    month = int(month_str[5:])
    month_index = year * 12 + (month - 1) + months
    return f"{month_index // 12}-{month_index % 12 + 1:02d}"


class CrimePredictionModel:
    """
    Singleton Class: CrimePredictionModel
    Represents a 3-tier ensemble model (70% XGBoost, 30% Random Forest).
    OPTIMIZED: Uses XGBoost's native backend for BOTH algorithms. No One-Hot Encoders!
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CrimePredictionModel, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return
        self._initialized = True
        self._reset_state()

    def _reset_state(self):
        self.is_trained = False
        self.period_start = None
        self.period_end = None
        self.last_data_month = None
        self.base_month_dt = None
        self.bias_month_count = 0
        
        self.models = {'xgb': {}, 'rf': {}}
        self.bias_factors = {'xgb': {}, 'rf': {}}
        self.tiers = {}
        
        self.unique_lsoas = []
        self.unique_crimes = []
        self.lsoa_cat_dtype = None
        self.crime_cat_dtype = None

    def status(self):
        if self.is_trained:
            print(f"model trained on period: {self.period_start} to {self.period_end}")
        else:
            print("model not trained yet")

    def trainAndBias(self, df):
        self._reset_state()
        print("\n[1/4] Validating and aggregating data...")

        required_cols = {'Month', 'LSOA code', 'Crime type'}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Input DataFrame is missing required columns. Need at least: {required_cols}")

        raw_agg = df.groupby(['Month', 'LSOA code', 'Crime type']).size().reset_index(name='Number of occurrences')

        all_months = sorted(raw_agg['Month'].unique().tolist())
        self.unique_lsoas = sorted(raw_agg['LSOA code'].unique())
        self.unique_crimes = sorted(raw_agg['Crime type'].unique())

        # Cartesian Product Zero-Fill
        full_idx = pd.MultiIndex.from_product(
            [all_months, self.unique_lsoas, self.unique_crimes], 
            names=['Month', 'LSOA code', 'Crime type']
        )
        full_df = pd.DataFrame(index=full_idx).reset_index()
        
        agg_df = pd.merge(full_df, raw_agg, on=['Month', 'LSOA code', 'Crime type'], how='left')
        agg_df['Number of occurrences'] = agg_df['Number of occurrences'].fillna(0)

        total_months = len(all_months)
        if total_months < 30:
            raise ValueError(f"Insufficient data: Requires at least 30 months. Found {total_months}.")

        self.period_start = all_months[0]
        self.period_end = all_months[-1]
        self.last_data_month = self.period_end
        self.base_month_dt = datetime.strptime(self.period_start, '%Y-%m')

        self.lsoa_cat_dtype = pd.CategoricalDtype(categories=self.unique_lsoas)
        self.crime_cat_dtype = pd.CategoricalDtype(categories=self.unique_crimes)

        agg_df = self._add_time_features(agg_df)

        train_months = all_months[:-6]
        bias_months = all_months[-6:]
        self.bias_month_count = len(bias_months)
        
        df_train = agg_df[agg_df['Month'].isin(train_months)].copy()
        df_bias = agg_df[agg_df['Month'].isin(bias_months)].copy()

        # =====================================================================
        # LOGARITHMIC TIER SPLITTING 
        # =====================================================================
        print("[2/4] Calculating Logarithmic Tier Split...")
        last_train_month = train_months[-1]
        lsoa_vol = df_train[df_train['Month'] == last_train_month].groupby('LSOA code')['Number of occurrences'].sum()
        lsoa_vol = lsoa_vol.reindex(self.unique_lsoas).fillna(0) 
        
        max_vol = max(1, lsoa_vol.max()) 
        
        thresh1 = 10 ** (np.log10(max_vol) / 3.0)
        thresh2 = 10 ** (2.0 * np.log10(max_vol) / 3.0)
        
        self.tiers['T3'] = lsoa_vol[lsoa_vol <= thresh1].index.tolist()
        self.tiers['T2'] = lsoa_vol[(lsoa_vol > thresh1) & (lsoa_vol <= thresh2)].index.tolist()
        self.tiers['T1'] = lsoa_vol[lsoa_vol > thresh2].index.tolist()
        
        print(f"      -> Max LSOA volume last month: {max_vol:.0f}")
        print(f"      -> T1 (High > {thresh2:.1f}): {len(self.tiers['T1'])} LSOAs")
        print(f"      -> T2 (Med {thresh1:.1f}-{thresh2:.1f}): {len(self.tiers['T2'])} LSOAs")
        print(f"      -> T3 (Low <= {thresh1:.1f}): {len(self.tiers['T3'])} LSOAs")

        # =====================================================================
        # NATIVE C++ TRAINING (NO ONE-HOT ENCODERS)
        # =====================================================================
        print("[3/4] Training Native C++ Models (Ultra-Fast)...")
        for tier_name in ['T1', 'T2', 'T3']:
            tier_lsoas = self.tiers[tier_name]
            if not tier_lsoas: continue

            print(f"      -> Processing {tier_name}...")
            tr = df_train[df_train['LSOA code'].isin(tier_lsoas)].copy()
            bi = df_bias[df_bias['LSOA code'].isin(tier_lsoas)].copy()

            if tr.empty: continue

            X_tr = self._prep_X(tr)
            
            # --- XGBoost ---
            xgb_model = xgb.XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.1,
                                         enable_categorical=True, tree_method='hist', verbosity=0)
            xgb_model.fit(X_tr, tr['Number of occurrences'])
            self.models['xgb'][tier_name] = xgb_model

            # --- XGBoost Random Forest (Optimized for Memory) ---
            rf_model = xgb.XGBRegressor(
                n_estimators=100, 
                max_depth=8, 
                subsample=0.8,      # RF behavior
                colsample_bytree=0.8,     # RF behavior
                enable_categorical=True, 
                tree_method="hist", 
                verbosity=0, 
                random_state=42
            )
            rf_model.fit(X_tr, tr["Number of occurrences"])
            self.models["rf"][tier_name] = rf_model

            # Bias Calculation
            if not bi.empty:
                X_bi = self._prep_X(bi)
                self.bias_factors['xgb'][tier_name] = self._calc_bias(xgb_model.predict(X_bi), bi['Number of occurrences'])
                self.bias_factors['rf'][tier_name] = self._calc_bias(rf_model.predict(X_bi), bi['Number of occurrences'])
            else:
                self.bias_factors['xgb'][tier_name] = 0.0
                self.bias_factors['rf'][tier_name] = 0.0

        self.is_trained = True
        print(f"[4/4] Success! Model trained on {len(train_months)} months with {self.bias_month_count} months bias.")

    def predict_month(self, month_str: str) -> pd.DataFrame:
        """Predicts a specific month string (e.g., '2026-05')"""
        if not self.is_trained:
            raise RuntimeError("Cannot predict: Model is not trained yet. Run trainAndBias() first.")

        all_combos = list(product(self.unique_lsoas, self.unique_crimes))
        df_pred = pd.DataFrame(all_combos, columns=['LSOA code', 'Crime type'])
        df_pred['Month'] = month_str
        df_pred = self._add_time_features(df_pred)

        xgb_all, rf_all = np.zeros(len(df_pred)), np.zeros(len(df_pred))

        for tier_name, tier_lsoas in self.tiers.items():
            mask = df_pred['LSOA code'].isin(tier_lsoas)
            idx = df_pred[mask].index
            if len(idx) == 0 or tier_name not in self.models['xgb']: continue

            tg = df_pred.loc[idx].copy()
            X_tg = self._prep_X(tg)

            xgb_p = self._apply_correction(self.models['xgb'][tier_name].predict(X_tg), self.bias_factors['xgb'][tier_name]).clip(min=0)
            xgb_all[idx] = xgb_p

            rf_p = self._apply_correction(self.models['rf'][tier_name].predict(X_tg), self.bias_factors['rf'][tier_name]).clip(min=0)
            rf_all[idx] = rf_p

        df_pred['XGB_Prediction'] = xgb_all
        df_pred['RF_Prediction'] = rf_all
        
        ensemble_raw = (xgb_all * 0.7 + rf_all * 0.3)
        df_pred['Ensemble_7030_Prediction'] = np.where(ensemble_raw < 0.3, 0, ensemble_raw)

        return df_pred[['Month', 'LSOA code', 'Crime type', 
                        'XGB_Prediction', 'RF_Prediction', 'Ensemble_7030_Prediction']]

    def predict_horizon(self, months_ahead: int) -> pd.DataFrame:
        """Loops through future months and aggregates the predictions"""
        predictions = []
        for i in range(1, months_ahead + 1):
            next_month = add_months(self.last_data_month, i)
            predictions.append(self.predict_month(next_month))
        return pd.concat(predictions, ignore_index=True)

    def save_xgb_models(self, output_dir: Path):
        """Saves the XGB and RF models to JSON format for the dashboard backend"""
        output_dir.mkdir(parents=True, exist_ok=True)
        for tier_name in ['T1', 'T2', 'T3']:
            if tier_name in self.models['xgb']:
                self.models['xgb'][tier_name].save_model(output_dir / f"xgb_tier_{tier_name}.json")
            if tier_name in self.models['rf']:
                self.models['rf'][tier_name].save_model(output_dir / f"rf_tier_{tier_name}.json")
        print("Exported JSON model weights successfully.")

    def _add_time_features(self, df):
        dates = pd.to_datetime(df['Month'])
        df['Month_Num'] = dates.dt.month
        df['Time_Index'] = (dates.dt.year - self.base_month_dt.year) * 12 + (dates.dt.month - self.base_month_dt.month)
        return df

    def _prep_X(self, df):
        X = df[['Time_Index', 'Month_Num', 'LSOA code', 'Crime type']].copy()
        X['LSOA code'] = X['LSOA code'].astype(self.lsoa_cat_dtype)
        X['Crime type'] = X['Crime type'].astype(self.crime_cat_dtype)
        return X

    def _calc_bias(self, preds_arr, actual_series):
        total = actual_series.sum()
        return float((preds_arr.sum() - total) / total) if total > 0 else 0.0

    def _apply_correction(self, preds_arr, factor):
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
    
    # Safe RMSE calculation that won't break on older scikit-learn versions
    rmse = np.sqrt(mean_squared_error(test_dashboard["actual_crimes"], test_dashboard["predicted_crimes"]))

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
        "xgb_tier_T1.json, rf_tier_T1.json, etc..."
    ]:
        print(f"- {args.output_dir / name}")


if __name__ == "__main__":
    main()
