"""
Train the selected 70/30 XGBoost crime forecasting model and export dashboard-ready files.

Expected project structure:

project/
├── test_data/
│   ├── 2025-01.csv
│   ├── 2025-02.csv
│   └── ...
│
│   OR:
│   ├── 2025-01/2025-01-city-of-london-street.csv
│   ├── 2025-02/2025-02-city-of-london-street.csv
│   └── ...
├── outputs/
└── train_forecast_model.py

Run from terminal:
    python train_forecast_model_one_year.py --data-dir test_data --output-dir outputs --forecast-months 12

Main outputs:
    outputs/model_evaluation_70_30.csv
    outputs/test_predictions_dashboard.csv
    outputs/forecast_dashboard_long.csv
    outputs/forecast_dashboard_long.json
    outputs/xgb_split_model_top5.json
    outputs/xgb_split_model_others.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error


TARGET_COL = "Number of occurrences"
FEATURES = ["Time_Index", "Month_Num", "LSOA code", "Crime type"]

XGB_PARAMS = dict(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.1,
    enable_categorical=True,
    tree_method="hist",
    objective="count:poisson",
    verbosity=0,
    random_state=42,
)


def find_monthly_csvs(data_dir: Path) -> List[Path]:
    """Find monthly UK Police CSV files inside data_dir.

    Works with both structures:
    - data/2025-01.csv
    - data/2025-01/2025-01-city-of-london-street.csv
    """
    import re
    all_csvs = sorted(data_dir.glob("**/*.csv"))

    # Only keep monthly crime files. This avoids static files like lsoa_to_ward.csv,
    # crime_category_weights.csv, etc.
    csvs = []
    for p in all_csvs:
        name_or_parent = f"{p.stem} {p.parent.name}"
        if re.search(r"20\d{2}-\d{2}", name_or_parent):
            csvs.append(p)

    if not csvs:
        raise FileNotFoundError(f"No monthly CSV files found inside {data_dir.resolve()}. Expected folders/files like 2025-01/2025-01-...-street.csv")
    return csvs


def infer_month_from_path(file_path: Path) -> str | None:
    """Infer YYYY-MM from a filename or parent folder like 2025-01.csv / 2025-01."""
    import re

    candidates = [file_path.stem, file_path.parent.name]
    for candidate in candidates:
        match = re.search(r"(20\d{2}-\d{2})", candidate)
        if match:
            return match.group(1)
    return None


def load_raw_crime_data(data_dir: Path) -> pd.DataFrame:
    """Load all monthly CSV files into one dataframe."""
    frames = []
    for file_path in find_monthly_csvs(data_dir):
        try:
            df = pd.read_csv(file_path, low_memory=False)

            # Some monthly files have a Month column. If not, infer it from the
            # filename/folder name, for example 2025-01.csv or data/2025-01/...
            if "Month" not in df.columns:
                inferred_month = infer_month_from_path(file_path)
                if inferred_month is not None:
                    df["Month"] = inferred_month

            if {"Month", "LSOA code", "Crime type"}.issubset(df.columns):
                frames.append(df[["Month", "LSOA code", "Crime type"]].copy())
            else:
                print(f"Skipping {file_path}: missing required columns")
        except Exception as exc:
            print(f"Skipping {file_path}: {exc}")

    if not frames:
        raise ValueError("No valid crime CSV files found. Required columns: Month, LSOA code, Crime type")

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.dropna(subset=["Month", "LSOA code", "Crime type"])
    raw["Month"] = raw["Month"].astype(str).str[:7]
    return raw


def aggregate_crimes(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw street-level crimes to Month x LSOA x Crime type counts."""
    df = (
        raw.groupby(["Month", "LSOA code", "Crime type"])
        .size()
        .reset_index(name=TARGET_COL)
    )
    return add_time_features(df)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add year, month number, and a chronological time index."""
    df = df.copy()
    df["Month"] = pd.to_datetime(df["Month"], format="%Y-%m")
    df["Year"] = df["Month"].dt.year
    df["Month_Num"] = df["Month"].dt.month

    first_month = df["Month"].min()
    df["Time_Index"] = (
        (df["Year"] - first_month.year) * 12
        + (df["Month_Num"] - first_month.month)
        + 1
    )
    df["Month"] = df["Month"].dt.strftime("%Y-%m")
    return df


def chronological_split(df: pd.DataFrame, train_ratio: float = 0.70) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Split by months, not randomly, so future months are tested on unseen time."""
    months = sorted(df["Month"].unique())
    split_idx = int(len(months) * train_ratio)
    train_months = months[:split_idx]
    test_months = months[split_idx:]

    if len(train_months) == 0 or len(test_months) == 0:
        raise ValueError("Not enough months for a 70/30 chronological split.")

    train_df = df[df["Month"].isin(train_months)].copy()
    test_df = df[df["Month"].isin(test_months)].copy()
    return train_df, test_df, months


def make_category_dtypes(df: pd.DataFrame) -> Dict[str, pd.CategoricalDtype]:
    return {
        "LSOA code": pd.CategoricalDtype(categories=sorted(df["LSOA code"].unique())),
        "Crime type": pd.CategoricalDtype(categories=sorted(df["Crime type"].unique())),
    }


def prepare_x(df: pd.DataFrame, cat_dtypes: Dict[str, pd.CategoricalDtype]) -> pd.DataFrame:
    X = df[FEATURES].copy()
    X["LSOA code"] = X["LSOA code"].astype(cat_dtypes["LSOA code"])
    X["Crime type"] = X["Crime type"].astype(cat_dtypes["Crime type"])
    return X


def train_split_xgboost(train_df: pd.DataFrame, cat_dtypes: Dict[str, pd.CategoricalDtype]):
    """Train separate XGBoost models for top 5 LSOAs and all other LSOAs."""
    top5_lsoas = (
        train_df.groupby("LSOA code")[TARGET_COL]
        .sum()
        .nlargest(5)
        .index.tolist()
    )

    train_top5 = train_df[train_df["LSOA code"].isin(top5_lsoas)].copy()
    train_others = train_df[~train_df["LSOA code"].isin(top5_lsoas)].copy()

    model_top5 = xgb.XGBRegressor(**XGB_PARAMS)
    model_others = xgb.XGBRegressor(**XGB_PARAMS)

    model_top5.fit(prepare_x(train_top5, cat_dtypes), train_top5[TARGET_COL])
    model_others.fit(prepare_x(train_others, cat_dtypes), train_others[TARGET_COL])

    return model_top5, model_others, top5_lsoas


def predict_split_model(df: pd.DataFrame, model_top5, model_others, top5_lsoas: List[str], cat_dtypes) -> np.ndarray:
    """Predict with top5 model for top5 LSOAs and others model for the rest."""
    preds = pd.Series(index=df.index, dtype=float)

    mask_top5 = df["LSOA code"].isin(top5_lsoas)
    if mask_top5.any():
        preds.loc[mask_top5] = model_top5.predict(prepare_x(df.loc[mask_top5], cat_dtypes))
    if (~mask_top5).any():
        preds.loc[~mask_top5] = model_others.predict(prepare_x(df.loc[~mask_top5], cat_dtypes))

    return preds.clip(lower=0).to_numpy()


def evaluate_model(test_df: pd.DataFrame, predictions: np.ndarray) -> pd.DataFrame:
    """Create a small evaluation table for the chosen 70/30 model."""
    mae = mean_absolute_error(test_df[TARGET_COL], predictions)
    mse = mean_squared_error(test_df[TARGET_COL], predictions)
    rmse = float(np.sqrt(mse))

    monthly = test_df[["Month", TARGET_COL]].copy()
    monthly["Prediction"] = predictions
    monthly_eval = monthly.groupby("Month")[[TARGET_COL, "Prediction"]].sum().reset_index()
    monthly_mae = mean_absolute_error(monthly_eval[TARGET_COL], monthly_eval["Prediction"])
    monthly_rmse = float(np.sqrt(mean_squared_error(monthly_eval[TARGET_COL], monthly_eval["Prediction"])))

    return pd.DataFrame([
        {
            "model": "XGBoost Split 70/30",
            "row_level_mae": mae,
            "row_level_mse": mse,
            "row_level_rmse": rmse,
            "monthly_total_mae": monthly_mae,
            "monthly_total_rmse": monthly_rmse,
            "test_months": test_df["Month"].nunique(),
            "test_rows": len(test_df),
        }
    ])


def make_future_rows(df: pd.DataFrame, forecast_months: int) -> pd.DataFrame:
    """Create future Month x LSOA x Crime type rows for dashboard forecasting."""
    last_month = pd.to_datetime(df["Month"].max(), format="%Y-%m")
    first_month = pd.to_datetime(df["Month"].min(), format="%Y-%m")
    future_months = pd.date_range(
        last_month + pd.DateOffset(months=1),
        periods=forecast_months,
        freq="MS",
    )

    lsoas = sorted(df["LSOA code"].unique())
    crime_types = sorted(df["Crime type"].unique())

    rows = []
    for month in future_months:
        time_index = (month.year - first_month.year) * 12 + (month.month - first_month.month) + 1
        for lsoa in lsoas:
            for crime_type in crime_types:
                rows.append({
                    "Month": month.strftime("%Y-%m"),
                    "Year": month.year,
                    "Month_Num": month.month,
                    "Time_Index": time_index,
                    "LSOA code": lsoa,
                    "Crime type": crime_type,
                })
    return pd.DataFrame(rows)


def save_dashboard_outputs(
    output_dir: Path,
    test_df: pd.DataFrame,
    test_predictions: np.ndarray,
    future_df: pd.DataFrame,
    future_predictions: np.ndarray,
    evaluation_df: pd.DataFrame,
    model_top5,
    model_others,
    top5_lsoas: List[str],
    cat_dtypes: Dict[str, pd.CategoricalDtype],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluation_df.to_csv(output_dir / "model_evaluation_70_30.csv", index=False)

    test_out = test_df[["Month", "LSOA code", "Crime type", TARGET_COL]].copy()
    test_out = test_out.rename(columns={TARGET_COL: "actual_crimes"})
    test_out["predicted_crimes"] = np.rint(test_predictions).astype(int)
    test_out["prediction_type"] = "test_70_30"
    test_out.to_csv(output_dir / "test_predictions_dashboard.csv", index=False)

    forecast_out = future_df[["Month", "LSOA code", "Crime type"]].copy()
    forecast_out["actual_crimes"] = np.nan
    forecast_out["predicted_crimes"] = np.rint(future_predictions).astype(int)
    forecast_out["prediction_type"] = "forecast_1_year"
    forecast_out.to_csv(output_dir / "forecast_dashboard_long.csv", index=False)
    forecast_out.to_json(output_dir / "forecast_dashboard_long.json", orient="records", indent=2)

    combined = pd.concat([test_out, forecast_out], ignore_index=True)
    combined.to_csv(output_dir / "dashboard_crime_predictions.csv", index=False)

    model_top5.save_model(output_dir / "xgb_split_model_top5.json")
    model_others.save_model(output_dir / "xgb_split_model_others.json")

    metadata = {
        "model": "XGBoost Split 70/30",
        "top5_lsoas": top5_lsoas,
        "features": FEATURES,
        "target": TARGET_COL,
        "lsoa_categories": list(cat_dtypes["LSOA code"].categories),
        "crime_type_categories": list(cat_dtypes["Crime type"].categories),
    }
    with open(output_dir / "model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="test_data", help="Folder containing monthly crime CSVs/folders, e.g. test_data/2025-01/...")
    parser.add_argument("--output-dir", default="outputs", help="Folder where outputs are saved")
    parser.add_argument("--forecast-months", type=int, default=12, help="Number of future months to forecast, normally 12 for one year")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    print("Loading raw crime data...")
    raw = load_raw_crime_data(data_dir)

    print("Aggregating data by Month, LSOA code, and Crime type...")
    df = aggregate_crimes(raw)
    print(f"Dataset: {df['Month'].min()} to {df['Month'].max()} | {df['Month'].nunique()} months | {len(df):,} rows")

    train_df, test_df, months = chronological_split(df, train_ratio=0.70)
    print(f"70/30 split: train {train_df['Month'].min()} to {train_df['Month'].max()} | test {test_df['Month'].min()} to {test_df['Month'].max()}")

    cat_dtypes = make_category_dtypes(df)

    print("Training selected split XGBoost model on 70% training period...")
    model_top5, model_others, top5_lsoas = train_split_xgboost(train_df, cat_dtypes)

    print("Testing model on final 30% period...")
    test_predictions = predict_split_model(test_df, model_top5, model_others, top5_lsoas, cat_dtypes)
    evaluation_df = evaluate_model(test_df, test_predictions)
    print(evaluation_df.to_string(index=False))

    print("Retraining selected model on the full dataset before forecasting...")
    final_top5_model, final_others_model, final_top5_lsoas = train_split_xgboost(df, cat_dtypes)

    print(f"Creating {args.forecast_months}-month forecast rows...")
    future_df = make_future_rows(df, args.forecast_months)
    future_predictions = predict_split_model(future_df, final_top5_model, final_others_model, final_top5_lsoas, cat_dtypes)

    print("Saving dashboard-ready outputs...")
    save_dashboard_outputs(
        output_dir=output_dir,
        test_df=test_df,
        test_predictions=test_predictions,
        future_df=future_df,
        future_predictions=future_predictions,
        evaluation_df=evaluation_df,
        model_top5=final_top5_model,
        model_others=final_others_model,
        top5_lsoas=final_top5_lsoas,
        cat_dtypes=cat_dtypes,
    )

    print(f"Done. Files saved in: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
