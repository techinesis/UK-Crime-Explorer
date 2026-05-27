import numpy as np
import pandas as pd
from scipy.optimize import linprog


class AllocationModel:
    def __init__(self, total_units: int, **options):
        self.total_units = total_units
        self.output_column = options.get("output_column", "units")

        return self

    def allocate(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


class AveragingModel(AllocationModel):
    def __init__(self, **options):
        super().__init__(**options)

        return self

    def allocate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = (
            df
            .groupby(["lsoa_code", "lsoa_name", "borough"])
            .agg(
                crime_count=("crime_count", "sum"),
                crime_types=("category", "nunique"),
            )
            .reset_index(drop=True)
        )

        TOTAL_CRIME = df["crime_count"].sum()
        df["crime_share"] = df["crime_count"] / TOTAL_CRIME
        df[self.output_column] = df["crime_share"] * self.total_units

        return df


class LPModel(AllocationModel):
    """
    This LP model aims to maximize weighted coverage and reward crime diversity by benefiting
    many crime types. Guarantees minimum coverage for each LSOA. Enforces a borough equity
    floor such that each borough receives at least 70% of its crime-proportional budget
    share
    We are solving the following objective:
     max_x a \sum_i s_i x_i / S + b \sum_i c_i x_i / C + c \sum_i d_i x_i / n
    such that
     \sum_i x_i = T
     x_i >= x^min
     x_i <= x_i^max
     ∀ borough : \sum_{lsoa \in borough} x_lsoa >= h * C_borough / C * T
    where
     s_i = weighted score (severity and preventability)
     c_i = crime count
     d_i = crime type diversity
     T = total budget
     h = equity floor ratio ("equity_floor" parameter)
    and a, b, c are parameters with the following decision making intuitions
     a = weight for weighted score ("alpha" parameter)
     b = weight for crime volume ("beta" parameter)
     c = weight for crime diversity ("gamma" parameter)
    we must have a + b + c = 1
    """

    def __init__(self, weighted_column: str, **options):
        super().__init__(**options)

        self.weighted_column = weighted_column

        self.min_units_per_lsoa = options.get("min_units_per_lsoa", 2)

        self.alpha = options.get("alpha", 0.6)
        self.beta = options.get("beta", 0.25)
        self.gamma = options.get("gamma", 0.15)

        self.max_cap_factor = options.get("max_cap_factor", 3.5)
        self.equity_floor = options.get("equity_floor", 0.7)

        return self

    def allocate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = (
            df
            .groupby(["lsoa_code", "lsoa_name", "borough"])
            .agg(
                crime_count=("crime_count", "sum"),
                score=(self.weighted_column, "sum"),
                crime_types=("category", "nunique"),
            )
            .reset_index(drop=True)
        )

        total_crime = df["crime_count"].sum()

        n_lsoas = len(df)
        s = df["score"].values
        c_crimes = df["crime_count"].values
        ct = df["crime_types"].values

        total_s = s.sum()
        max_ct = ct.max()

        diversity = ct / max_ct

        c = -(
            self.alpha * s / total_s
            + self.beta * c_crimes / total_crime
            + self.gamma * diversity / (diversity.sum() / n_lsoas)
        )

        sev_proportional = (s / total_s) * self.total_units
        bounds_lp = [
            (self.min_units_per_lsoa, ub)
            for ub in np.maximum(10.0, self.max_cap_factor * sev_proportional)
        ]

        boroughs = df["borough"].unique()
        borough_crime_sum = df.groupby("borough")["crime_count"].sum()

        A_eq = np.ones((1, n_lsoas))
        b_eq = np.array([self.total_units])
        A_ub = []
        b_ub = []

        for borough in boroughs:
            mask = (df["borough"] == borough).values
            bor_share = borough_crime_sum[borough] / total_crime
            floor = self.equity_floor * bor_share * self.total_units
            A_ub.append(-mask)
            b_ub.append(-floor)

        A_ub = np.array(A_ub)
        b_ub = np.array(b_ub)

        res = linprog(
            c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds_lp,
            method="highs",
            options={"disp": False},
        )

        df[self.output_column] = res.x

        return df


class RawlsModel(AllocationModel):
    """
    A model derived from John Rawls' second principle of Justice as Fairness. More specifically
    the difference principle:
        > They are to be to the greatest benefit of the least-advantaged members of society.

    In this way, we maximize z where z is the "fraction of proportional entitlement" that every
    LSOA receives. The entitlement is essentially a measure of how much a given LSOA would be
    allocated in the standard baseline model given the score s_i. So it "improves" on the baseline
    by benefiting LSOAs that would have originally been given a lesser allocation.

    We are solving the following objective:
     max_{x, z} z
    such that
     forall i : x_i >= z * ent_i
     \sum_i x_i = T
     x_i >= x^min
     z \in [0, 1]
    where
     ent_i = s_i * T / S
    """

    def __init__(self, weighted_column: str, **options):
        super().__init__(**options)

        self.weighted_column = weighted_column
        self.min_units_per_lsoa = options.get("min_units_per_lsoa", 2)

        return self

    def allocate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = (
            df
            .groupby(["lsoa_code", "lsoa_name", "borough"])
            .agg(
                crime_count=("crime_count", "sum"),
                score=(self.weighted_column, "sum"),
                crime_types=("category", "nunique"),
            )
            .reset_index(drop=True)
        )

        n = len(df)
        s = df["score"].values
        total_s = s.sum()

        s_entitlement = (s / total_s) * self.total_units

        c = np.zeros(n + 1)
        c[-1] = -1.0

        bounds_mm = [(self.min_units_per_lsoa, None)] * n + [(0.0, 1.0)]

        A_eq = np.zeros((1, n + 1))
        A_eq[0, :n] = 1.0
        b_eq = np.array([self.total_units])

        A_ub = np.zeros((n, n + 1))
        for i in range(n):
            A_ub[i, i] = -1.0
            A_ub[i, -1] = s_entitlement[i]
        b_ub = np.zeros(n)

        res = linprog(
            c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds_mm,
            method="highs",
        )

        df[self.output_column] = res.x[:n]

        return df


def allocate(model: AllocationModel, df: pd.DataFrame, **options):
    return model.allocate(df, **options)
