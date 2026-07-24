#!/usr/bin/env python3
"""
inspect_metadata.py

Explore a metadata CSV without assuming its columns.
"""

from pathlib import Path

import pandas as pd


def inspect_metadata(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    print("=" * 70)
    print("DATASET OVERVIEW")
    print("=" * 70)

    print(f"Rows    : {len(df):,}")
    print(f"Columns : {len(df.columns)}")

    print("\nColumn names")
    print("-" * 70)

    for column in df.columns:
        print(column)

    print("\nData types")
    print("-" * 70)

    print(df.dtypes)

    print("\nMissing values")
    print("-" * 70)

    print(df.isna().sum())

    print("\nDuplicate rows")
    print("-" * 70)

    print(df.duplicated().sum())

    print("\nFirst five rows")
    print("-" * 70)

    print(df.head())

    return df


def summarize_numeric(df: pd.DataFrame) -> None:

    numeric = df.select_dtypes(include="number")

    if numeric.empty:
        print("\nNo numeric columns found.")
        return

    print("\nNumeric summary")
    print("-" * 70)

    print(numeric.describe())


def summarize_categorical(df: pd.DataFrame) -> None:

    categorical = df.select_dtypes(exclude="number")

    if categorical.empty:
        print("\nNo categorical columns found.")
        return

    for column in categorical.columns:

        print("\n" + "=" * 70)
        print(column)
        print("=" * 70)

        print(categorical[column].value_counts(dropna=False))


def main() -> None:

    path = Path("soil_metadata.csv")

    df = inspect_metadata(path)

    summarize_numeric(df)

    summarize_categorical(df)


if __name__ == "__main__":
    main()
