"""Derive severity weights from the Cambridge Crime Harm Index (CCHI) 2020.

Source: data/cchi2020dataxls.xlsx — Cambridge Centre for Evidence-Based Policing,
current with England and Wales sentencing guidelines as of 2020-10-06. Each row
is a notifiable offence; CCHI Score is the recommended starting-point sentence
in days.

Method: for each major_category in the user's 2008–2016 Met dataset, identify
which CCHI GROUP values cover that category, then take the offence-count-
weighted mean CCHI Score across all matched offences. This preserves the
total-harm identity (Σ count × score) under the assumption that the within-
category offence mix is roughly uniform across LSOAs — a placeholder
assumption that should be replaced when offence-level frequency data is
available.

Preventability multipliers and tiers come from the expansion spec's first-pass
mapping for the 9-category Met taxonomy. Sub-question 4 will replace these
once finalized.

Run: `python prepare_category_weights.py`
"""

from __future__ import annotations

import pandas as pd

CCHI_PATH = "data/cchi2020dataxls.xlsx"
CCHI_SHEET = "CCHI 2020 values sheet"
OUTPUT_PATH = "data/category_weights.csv"

CATEGORY_TO_CCHI_GROUPS: dict[str, list[str]] = {
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

PREVENTABILITY_DEFAULTS: dict[str, tuple[str, float]] = {
    "Burglary":                    ("Medium", 0.5),
    "Criminal Damage":             ("Low",    0.1),
    "Drugs":                       ("Low",    0.1),
    "Fraud or Forgery":            ("Low",    0.1),
    "Other Notifiable Offences":   ("Low",    0.1),
    "Robbery":                     ("High",   1.0),
    "Sexual Offences":             ("Low",    0.1),
    "Theft and Handling":          ("Medium", 0.5),
    "Violence Against the Person": ("Low",    0.1),
}


def main() -> None:
    cchi = pd.read_excel(CCHI_PATH, sheet_name=CCHI_SHEET, header=0)
    cchi.columns = [str(c).strip() for c in cchi.columns]

    rows = []
    for category, groups in CATEGORY_TO_CCHI_GROUPS.items():
        offences = cchi[cchi["GROUP"].isin(groups)]
        scores = offences["CCHI Score"].dropna()

        if scores.empty:
            raise ValueError(
                f"No CCHI offences matched for {category!r} "
                f"(groups: {groups})"
            )

        severity = round(float(scores.mean()), 2)
        tier, multiplier = PREVENTABILITY_DEFAULTS[category]

        rows.append(
            {
                "major_category": category,
                "severity_weight": severity,
                "preventability_multiplier": multiplier,
                "preventability_tier": tier,
            }
        )

    weights = (
        pd.DataFrame(rows)
        .sort_values("major_category")
        .reset_index(drop=True)
    )
    weights.to_csv(OUTPUT_PATH, index=False)

    print(weights.to_string(index=False))
    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
