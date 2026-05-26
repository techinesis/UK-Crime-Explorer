"""Derive category weights for the dashboard from the Cambridge Crime Harm
Index (CCHI) 2020 plus a literature-anchored preventability table.

This script is hybrid — it auto-detects whether the active raw crime CSV uses
the legacy 9-category MPS taxonomy ("Theft and Handling", "Violence Against
the Person", ...) or the modern 14-category data.police.uk taxonomy ("Bicycle
theft", "Anti-social behaviour", ...) and emits a matching
``data/category_weights.csv`` with the same 7-column schema in either case:

    category,
    severity_weight_mean, severity_weight_median,
    preventability_multiplier, preventability_tier,
    preventability_confidence, preventability_anchor

Severity weights are unweighted mean and median CCHI scores (in days of
recommended sentence) across the CCHI offences that map to each category.
The "offence-count-weighted" label used elsewhere in the project requires
per-offence frequency data the CCHI sheet does not expose, so weights are
uniform across the offence definitions inside each GROUP. This is documented
in the dashboard footer.

Categories with no CCHI mapping — currently only "Anti-social behaviour" in
the 14-schema, which is non-notifiable and outside CCHI's scope — emit
``NaN`` for both severity columns; the app coerces these to 0 at display
time and a footer caveat names the affected categories.

Preventability multipliers, confidences, and one-line anchors come from the
Dashboard Expansion Spec's literature review:

* Braga, Turchan, Papachristos & Hureau (2019) — Campbell SR meta-analysis
  of hot-spot policing: disorder ES = 0.161, drug crime ES = 0.244,
  violent crime ES = 0.102.
* Weisburd (2015) — crime concentration in micro-places: e.g., 100% of
  robberies recorded in 2.2% of places, 100% of vehicle crime in 2.7%.
* Sherman, Neyroud & Neyroud (2016) — CCHI methodology.

Tiers are derived from multiplier thresholds at *runtime* (>=0.9 High,
>=0.4 Medium, <0.4 Low), not hard-coded — change a multiplier and the tier
auto-updates.

Run: ``python prepare_category_weights.py``
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

CCHI_PATH = "data/cchi2020dataxls.xlsx"
CCHI_SHEET = "CCHI 2020 values sheet"
CRIME_CSV_PATH = ".cache/crime-data/london_crime_by_lsoa.csv"
OUTPUT_PATH = "data/category_weights.csv"


# Legacy 9-category MPS taxonomy used by the 2008-2016 Kaggle dataset.
CCHI_GROUPS_9: dict[str, list[str]] = {
    "Burglary": ["BURGLARY"],
    "Criminal Damage": ["ARSON AND CRIMINAL DAMAGE"],
    "Drugs": ["DRUG OFFENCES"],
    "Fraud or Forgery": ["FRAUD AND FORGERY", "NFIB FRAUD"],
    "Other Notifiable Offences": [
        "MISCELLANEOUS CRIMES AGAINST SOCIETY",
        "POSSESSION OF WEAPONS",
        "PUBLIC ORDER OFFENCES",
    ],
    "Robbery": ["ROBBERY"],
    "Sexual Offences": ["SEXUAL OFFENCES"],
    "Theft and Handling": ["THEFT", "VEHICLE OFFENCES"],
    "Violence Against the Person": ["VIOLENCE AGAINST THE PERSON"],
}


# Modern 14-category data.police.uk taxonomy. "Anti-social behaviour" is
# non-notifiable and has no CCHI GROUP — kept here with an empty list so the
# row still appears in the output CSV with NaN severity.
CCHI_GROUPS_14: dict[str, list[str]] = {
    "Anti-social behaviour": [],
    "Bicycle theft": ["THEFT"],
    "Burglary": ["BURGLARY"],
    "Criminal damage and arson": ["ARSON AND CRIMINAL DAMAGE"],
    "Drugs": ["DRUG OFFENCES"],
    "Other crime": [
        "MISCELLANEOUS CRIMES AGAINST SOCIETY",
        "FRAUD AND FORGERY",
        "NFIB FRAUD",
    ],
    "Other theft": ["THEFT"],
    "Possession of weapons": ["POSSESSION OF WEAPONS"],
    "Public order": ["PUBLIC ORDER OFFENCES"],
    "Robbery": ["ROBBERY"],
    "Shoplifting": ["THEFT"],
    "Theft from the person": ["THEFT"],
    "Vehicle crime": ["VEHICLE OFFENCES"],
    "Violence and sexual offences": [
        "VIOLENCE AGAINST THE PERSON",
        "SEXUAL OFFENCES",
    ],
}


# (multiplier, confidence, one-line anchor). Tier is derived from multiplier.
PREVENTABILITY_9: dict[str, tuple[float, str, str]] = {
    "Burglary":                    (0.5, "High",   "Weisburd 2021 (MIT review): +10% presence -> -5 to -6%"),
    "Criminal Damage":             (0.4, "Medium", "Vandalism deterrable; Braga 2019 disorder ES = 0.161"),
    "Drugs":                       (0.3, "Low",    "Braga 2019 ES = 0.244 (open-air markets); UK transferability uncertain"),
    "Fraud or Forgery":            (0.1, "High",   "Mostly online / non-place-based; not patrol-deterrable"),
    "Other Notifiable Offences":   (0.2, "Low",    "Heterogeneous administrative bucket"),
    "Robbery":                     (1.0, "High",   "Weisburd 2015: 100% of robberies in 2.2% of places"),
    "Sexual Offences":             (0.1, "High",   "Mostly indoor / domestic; Braga 2019 violent ES = 0.102"),
    "Theft and Handling":          (0.7, "Medium", "Public theft visible-presence deterrable; mixed bag"),
    "Violence Against the Person": (0.1, "High",   "Mostly indoor / domestic; Braga 2019 violent ES = 0.102"),
}


PREVENTABILITY_14: dict[str, tuple[float, str, str]] = {
    "Anti-social behaviour":        (1.0, "High",   "Braga 2019 disorder ES = 0.161"),
    "Bicycle theft":                (0.9, "Medium", "UK reductions 19-60%; Weisburd concentration"),
    "Burglary":                     (0.5, "High",   "Weisburd 2021 (MIT review): +10% presence -> -5 to -6%"),
    "Criminal damage and arson":    (0.4, "Medium", "Vandalism deterrable; Braga 2019 disorder ES = 0.161"),
    "Drugs":                        (0.3, "Low",    "Braga 2019 ES = 0.244 (open-air markets, not UK records)"),
    "Other crime":                  (0.1, "Low",    "Heterogeneous administrative bucket"),
    "Other theft":                  (0.4, "Low",    "Heterogeneous catch-all; conservative weight"),
    "Possession of weapons":        (0.2, "Medium", "Stop-and-search literature, not patrol literature"),
    "Public order":                 (1.0, "High",   "Classic disorder-policing target; Braga 2019 ES = 0.161"),
    "Robbery":                      (1.0, "High",   "Weisburd 2015: 100% of robberies in 2.2% of places"),
    "Shoplifting":                  (0.7, "Medium", "Indoor but visible-presence deterrable"),
    "Theft from the person":        (0.7, "Medium", "Public pickpocketing / snatch theft, deterrable"),
    "Vehicle crime":                (0.9, "Medium", "Weisburd 2015: 100% of vehicle crime in 2.7% of places"),
    "Violence and sexual offences": (0.1, "High",   "Braga 2019 violent ES = 0.102; mostly indoor / domestic"),
}

# Signature names used to disambiguate schemas. Each set must contain names
# that are unique to its schema (cannot appear in the other one).
SCHEMA_9_MARKERS = frozenset({
    "Theft and Handling",
    "Violence Against the Person",
    "Other Notifiable Offences",
    "Fraud or Forgery",
    "Criminal Damage",
    "Sexual Offences",
})
SCHEMA_14_MARKERS = frozenset({
    "Anti-social behaviour",
    "Bicycle theft",
    "Public order",
    "Theft from the person",
    "Vehicle crime",
    "Violence and sexual offences",
    "Criminal damage and arson",
    "Possession of weapons",
})


def detect_schema(crime_csv_path: str) -> str:
    """Return ``"9"`` or ``"14"`` based on the unique ``category``
    values present in ``crime_csv_path``. Reads only the relevant column to
    keep memory/IO bounded on the 13.5M-row legacy CSV.
    """
    def load_csv():
        df = pd.read_csv(crime_csv_path, usecols=["major_category"]).rename(
            columns={"major_category": "category"}
        )
        SCHEMA_9_TO_14 = {
            # Violent Crime & Sexual Offenses
            "Assault with Injury": "Violence and sexual offences",
            "Common Assault": "Violence and sexual offences",
            "Murder": "Violence and sexual offences",
            "Other violence": "Violence and sexual offences",
            "Wounding/GBH": "Violence and sexual offences",
            "Harassment": "Violence and sexual offences",
            "Rape": "Violence and sexual offences",
            "Other Sexual": "Violence and sexual offences",
            # Property Crimes
            "Burglary in Other Buildings": "Burglary",
            "Burglary in a Dwelling": "Burglary",
            "Business Property": "Robbery",
            "Personal Property": "Robbery",
            # Theft & Shoplifting
            "Theft From Shops": "Shoplifting",
            "Theft/Taking of Pedal Cycle": "Bicycle theft",
            "Other Theft Person": "Theft from the person",
            "Other Theft": "Other theft",
            "Handling Stolen Goods": "Other theft",
            # Vehicle Crime
            "Motor Vehicle Interference & Tampering": "Vehicle crime",
            "Theft From Motor Vehicle": "Vehicle crime",
            "Theft/Taking Of Motor Vehicle": "Vehicle crime",
            # Criminal Damage
            "Criminal Damage To Dwelling": "Criminal damage and arson",
            "Criminal Damage To Motor Vehicle": "Criminal damage and arson",
            "Criminal Damage To Other Building": "Criminal damage and arson",
            "Other Criminal Damage": "Criminal damage and arson",
            # Drugs & Weapons
            "Drug Trafficking": "Drugs",
            "Other Drugs": "Drugs",
            "Possession Of Drugs": "Drugs",
            "Offensive Weapon": "Possession of weapons",
            "Going Equipped": "Other crime",
            # Others
            "Other Fraud & Forgery": "Other crime",
            "Other Notifiable": "Other crime",
            "Counted per Victim": "Other crime",
        }
        df["category"] = df["category"].map(SCHEMA_9_TO_14).fillna("other-crime")
        return df

    crime_df = load_csv()

    cats = set(
        crime_df["category"]
        .dropna()
        .unique()
    )
    has_9 = bool(cats & SCHEMA_9_MARKERS)
    has_14 = bool(cats & SCHEMA_14_MARKERS)
    if has_14 and not has_9:
        return "14"
    if has_9 and not has_14:
        return "9"
    raise ValueError(
        "Cannot disambiguate schema from category values. "
        f"Found {len(cats)} unique values: {sorted(cats)}"
    )


def derive_tier(multiplier: float) -> str:
    """Spec lines 325-331: tier follows from the multiplier, not the other
    way round. Recompute on every run so a sensitivity tweak (e.g., Drugs
    0.3 -> 0.5) auto-promotes Low -> Medium without a separate edit.
    """
    if multiplier >= 0.9:
        return "High"
    if multiplier >= 0.4:
        return "Medium"
    return "Low"


def compute_severity(
    cchi: pd.DataFrame, groups: list[str]
) -> tuple[float | None, float | None]:
    """Return ``(mean, median)`` CCHI score across all offences whose GROUP
    is in ``groups``. Both values are uniform-weighted across CCHI rows
    (the sheet has no per-offence frequency column). Returns ``(None,
    None)`` when ``groups`` is empty (e.g., Anti-social behaviour) or when
    no CCHI row matches.
    """
    if not groups:
        return None, None
    offences = cchi[cchi["GROUP"].isin(groups)]
    scores = offences["CCHI Score"].dropna()
    if scores.empty:
        return None, None
    return round(float(scores.mean()), 2), round(float(scores.median()), 2)


def build_rows(
    schema: str,
    cchi: pd.DataFrame,
    cchi_groups: Mapping[str, list[str]],
    preventability: Mapping[str, tuple[float, str, str]],
) -> list[dict]:
    rows: list[dict] = []
    for category, groups in cchi_groups.items():
        mean_val, median_val = compute_severity(cchi, groups)
        multiplier, confidence, anchor = preventability[category]
        tier = derive_tier(multiplier)
        rows.append(
            {
                "category": category,
                "severity_weight_mean": mean_val,
                "severity_weight_median": median_val,
                "preventability_multiplier": multiplier,
                "preventability_tier": tier,
                "preventability_confidence": confidence,
                "preventability_anchor": anchor,
            }
        )
        groups_label = ", ".join(groups) if groups else "(none — non-notifiable)"
        print(
            f"  [{schema}] {category!r}: groups=[{groups_label}] "
            f"mean={mean_val} median={median_val} "
            f"mult={multiplier} tier={tier} conf={confidence}"
        )
    return rows


def main() -> None:
    schema = detect_schema(CRIME_CSV_PATH)
    print(f"Detected schema: {schema}-category")

    if schema == "14":
        cchi_groups: Mapping[str, list[str]] = CCHI_GROUPS_14
        preventability: Mapping[str, tuple[float, str, str]] = PREVENTABILITY_14
    else:
        cchi_groups = CCHI_GROUPS_9
        preventability = PREVENTABILITY_9

    cchi = pd.read_excel(CCHI_PATH, sheet_name=CCHI_SHEET, header=0)
    cchi.columns = [str(c).strip() for c in cchi.columns]

    rows = build_rows(schema, cchi, cchi_groups, preventability)

    weights = (
        pd.DataFrame(rows)
        .sort_values("category")
        .reset_index(drop=True)
    )
    weights.to_csv(OUTPUT_PATH, index=False)

    print()
    print(weights.to_string(index=False))
    print(f"\nWrote {OUTPUT_PATH} with {len(weights)} rows ({schema}-schema)")


if __name__ == "__main__":
    main()
