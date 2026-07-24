#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""
taxonomy_queries.py

Utilities for querying taxonomic assignment tables
produced by QIIME2 and similar microbiome pipelines.

Author
------
Jan Ephraim R. Vallente
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


class TaxonomyError(ValueError):
    """Raised when a taxonomy table is malformed."""


class TaxonomyDatabase:
    """
    Represents a taxonomy assignment table.

    Parameters
    ----------
    taxonomy_file
        Path to the taxonomy CSV/TSV file.
    """

    REQUIRED_COLUMNS = (
        "Feature ID",
        "Kingdom",
        "Phylum",
        "Class",
        "Order",
        "Family",
        "Genus",
        "Species",
    )

    # ---------------------------------------------------------

    def __init__(self, taxonomy_file: Path):

        self.taxonomy_file = taxonomy_file

        self.df: pd.DataFrame | None = None

    # ---------------------------------------------------------

    def load(self) -> None:
        """
        Read the taxonomy table.

        Supports both CSV and TSV automatically.
        """

        try:

            self.df = pd.read_csv(
                self.taxonomy_file,
                sep=None,
                engine="python",
            )

        except FileNotFoundError:

            raise FileNotFoundError(
                f"Cannot locate taxonomy table:\n" f"{self.taxonomy_file}"
            ) from None

        except pd.errors.EmptyDataError:

            raise TaxonomyError("Taxonomy table is empty.") from None

        except pd.errors.ParserError:

            raise TaxonomyError("Unable to parse taxonomy table.") from None

        self._validate()

    # ---------------------------------------------------------

    def _validate(self) -> None:
        """
        Validate the structure of the taxonomy table.
        """

        assert self.df is not None

        if self.df.empty:

            raise TaxonomyError("The taxonomy table contains no records.")

        missing = [
            column for column in self.REQUIRED_COLUMNS if column not in self.df.columns
        ]

        if missing:

            raise TaxonomyError("Missing required columns:\n" + "\n".join(missing))

        duplicated = self.df["Feature ID"].duplicated()

        if duplicated.any():

            duplicates = self.df.loc[
                duplicated,
                "Feature ID",
            ].tolist()

            raise TaxonomyError(
                "Duplicate Feature IDs detected.\n" + "\n".join(duplicates[:10])
            )

    # ---------------------------------------------------------

    @property
    def number_of_features(self) -> int:

        assert self.df is not None

        return len(self.df)

    # ---------------------------------------------------------

    @property
    def taxonomic_ranks(self) -> list[str]:

        return list(self.REQUIRED_COLUMNS[1:])

    # ---------------------------------------------------------

    def summary(self) -> None:

        print()

        print("=" * 60)
        print("TAXONOMY TABLE SUMMARY")
        print("=" * 60)

        print(f"Input file : " f"{self.taxonomy_file.name}")

        print(f"Features   : " f"{self.number_of_features:,}")

        print()

        print("Taxonomic ranks:")

        for rank in self.taxonomic_ranks:

            print(f"  • {rank}")

        print("=" * 60)

    # ---------------------------------------------------------

    def _check_rank(
        self,
        rank: str,
    ) -> None:
        """
        Validate a requested taxonomic rank.
        """

        if rank not in self.taxonomic_ranks:

            raise ValueError(f"Unknown taxonomic rank: {rank}")

    # ---------------------------------------------------------

    def find_taxon(
        self,
        rank: str,
        value: str,
    ) -> pd.DataFrame:
        """
        Return every record matching a taxon.

        Example
        -------
        find_taxon(
            "Genus",
            "Bacillus",
        )
        """

        assert self.df is not None

        self._check_rank(rank)

        return self.df.loc[
            self.df[rank].fillna("").str.casefold() == value.casefold()
        ].copy()

    # ---------------------------------------------------------

    def count_taxa(
        self,
        rank: str,
        drop_unknown: bool = True,
    ) -> pd.Series:
        """
        Count the number of Feature IDs assigned to each taxon.

        Parameters
        ----------
        rank
            Taxonomic rank.

        drop_unknown
            Ignore missing assignments.
        """

        assert self.df is not None

        self._check_rank(rank)

        column = self.df[rank]

        if drop_unknown:
            column = column.dropna()

            column = column[column.str.strip() != ""]

        return column.value_counts().sort_values(ascending=False)

    # ---------------------------------------------------------

    def top_taxa(
        self,
        rank: str,
        n: int = 20,
    ) -> pd.Series:
        """
        Return the n most common taxa.
        """

        return self.count_taxa(rank).head(n)

    # ---------------------------------------------------------

    def unique_taxa(
        self,
        rank: str,
    ) -> list[str]:
        """
        Return every unique taxon at one rank.
        """

        assert self.df is not None

        self._check_rank(rank)

        return sorted(self.df[rank].dropna().unique().tolist())

    # ---------------------------------------------------------

    def unknown_taxa(
        self,
        rank: str,
    ) -> pd.DataFrame:
        """
        Return every Feature ID lacking
        an assignment at one rank.
        """

        assert self.df is not None

        self._check_rank(rank)

        return self.df.loc[self.df[rank].isna()].copy()

    # ---------------------------------------------------------

    def classification_completeness(
        self,
    ) -> pd.DataFrame:
        """
        Percentage of Feature IDs classified
        at each taxonomic rank.
        """

        assert self.df is not None

        rows = []

        total = len(self.df)

        for rank in self.taxonomic_ranks:

            classified = self.df[rank].notna().sum()

            rows.append(
                {
                    "Rank": rank,
                    "Assigned": classified,
                    "Missing": total - classified,
                    "PercentAssigned": classified / total * 100,
                }
            )

        return pd.DataFrame(rows)

    # ---------------------------------------------------------

    def summary_by_rank(
        self,
        rank: str,
    ) -> pd.DataFrame:
        """
        Produce a summary for one taxonomic rank.
        """

        counts = self.count_taxa(rank)

        return pd.DataFrame(
            {
                "Taxon": counts.index,
                "FeatureCount": counts.values,
            }
        )

    # ---------------------------------------------------------

    def export_summary(
        self,
        rank: str,
        output: Path,
    ) -> None:
        """
        Export one taxonomic summary.
        """

        table = self.summary_by_rank(rank)

        table.to_csv(
            output,
            index=False,
        )

    # ---------------------------------------------------------

    def export_completeness(
        self,
        output: Path,
    ) -> None:
        """
        Export completeness report.
        """

        table = self.classification_completeness()

        table.to_csv(
            output,
            index=False,
        )


# ---------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query a microbial taxonomy table.",
        epilog="""
Examples:

  Show a summary
    %(prog)s soil.tax.csv --summary

  Count all phyla
    %(prog)s soil.tax.csv --rank Phylum --count

  Show the 10 most common genera
    %(prog)s soil.tax.csv --rank Genus --top 10

  Find every Proteobacteria feature
    %(prog)s soil.tax.csv --rank Phylum --find Proteobacteria

  Show missing species assignments
    %(prog)s soil.tax.csv --rank Species --missing

  Export genus counts
    %(prog)s soil.tax.csv --rank Genus --count --export genus_counts.csv
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "taxonomy",
        type=Path,
        help="Taxonomy CSV/TSV file.",
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help="Display table summary.",
    )

    parser.add_argument(
        "--rank",
        choices=[
            "Kingdom",
            "Phylum",
            "Class",
            "Order",
            "Family",
            "Genus",
            "Species",
        ],
        help="Taxonomic rank.",
    )

    parser.add_argument(
        "--find",
        metavar="NAME",
        help="Find records matching the specified taxon (requires --rank).",
    )

    parser.add_argument(
        "--count",
        action="store_true",
        help="Count taxa for the rank specified by --rank.",
    )

    parser.add_argument(
        "--top",
        type=int,
        metavar="N",
        help="Show the N most common taxa.",
    )

    parser.add_argument(
        "--missing",
        action="store_true",
        help="Show Feature IDs lacking an assignment at the rank specified by --rank.",
    )

    parser.add_argument(
        "--completeness",
        action="store_true",
        help="Show taxonomic completeness.",
    )

    parser.add_argument(
        "--export",
        type=Path,
        help=("Output CSV filename " "(example: --export phylum_counts.csv)."),
    )

    return parser


# ---------------------------------------------------------


def main() -> None:

    parser = build_parser()
    args = parser.parse_args()

    if any((args.count, args.top, args.find, args.missing)) and args.rank is None:
        parser.error("--count, --top, --find, and --missing require --rank.")

    db = TaxonomyDatabase(args.taxonomy)
    db.load()

    if args.summary:
        db.summary()

    if args.completeness:

        table = db.classification_completeness()

        print()
        print(table.to_string(index=False))

        if args.export:
            db.export_completeness(args.export)

    if args.rank:

        if args.count:

            table = db.summary_by_rank(args.rank)

            print()
            print(table.to_string(index=False))

            if args.export:
                db.export_summary(
                    args.rank,
                    args.export,
                )

        if args.top:

            print()
            print(
                db.top_taxa(
                    args.rank,
                    args.top,
                )
            )

        if args.find:

            result = db.find_taxon(
                args.rank,
                args.find,
            )

            if result.empty:

                print(f"\nNo matches for " f"{args.find!r}")

            else:

                print()
                print(result.to_string(index=False))

        if args.missing:

            missing = db.unknown_taxa(args.rank)

            print()

            if missing.empty:

                print(f"No missing {args.rank} " "assignments.")

            else:

                print(missing.to_string(index=False))


# ---------------------------------------------------------

if __name__ == "__main__":
    try:
        main()

    except (
        TaxonomyError,
        FileNotFoundError,
        PermissionError,
        ValueError,
    ) as exc:

        sys.exit(str(exc))
