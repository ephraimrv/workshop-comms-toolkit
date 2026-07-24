#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""
OTU Analyzer

A command-line utility for exploring Operational Taxonomic Unit (OTU)
abundance tables generated from microbial community sequencing.

Features
--------
* Validate OTU tables
* Compute sequencing depth
* Compute richness
* Compute prevalence
* Compute total abundance
* Compute relative abundance
* Filter rare OTUs
* Export analysis reports

Author
------
Jan Ephraim R. Vallente
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


class OTUTableError(ValueError):
    """Raised when an OTU table is malformed."""


class OTUAnalyzer:
    """
    Analyze an OTU abundance table.

    Parameters
    ----------
    csv_file : Path
        Path to the OTU table.
    """

    def __init__(self, csv_file: Path) -> None:

        self.csv_file = csv_file

        self.df: pd.DataFrame | None = None

        self.sample_columns: list[str] = []

    # ---------------------------------------------------------

    def load(self) -> None:
        """
        Read the OTU table into memory.
        """
        try:
            self.df = pd.read_csv(
                self.csv_file,
                sep=None,
                engine="python",
            )

        except FileNotFoundError:

            raise FileNotFoundError(
                f"Cannot locate OTU table:\n{self.csv_file}"
            ) from None

        except pd.errors.EmptyDataError:

            raise OTUTableError("Input CSV is empty.") from None

        except pd.errors.ParserError:

            raise OTUTableError("CSV parser failed. File is malformed.") from None

        self._validate()

    # ---------------------------------------------------------

    def _validate(self) -> None:
        """
        Validate the structure of the OTU table.
        """

        assert self.df is not None

        if self.df.empty:

            raise OTUTableError("OTU table contains no rows.")

        if "OTUID" not in self.df.columns:

            raise OTUTableError("Missing required 'OTUID' column.")

        self.sample_columns = [
            column for column in self.df.columns if column != "OTUID"
        ]

        if len(self.sample_columns) == 0:

            raise OTUTableError("No sample columns detected.")

        duplicated = self.df["OTUID"].duplicated()

        if duplicated.any():

            duplicates = self.df.loc[duplicated, "OTUID"].tolist()

            raise OTUTableError(
                "Duplicate OTU IDs detected:\n" + "\n".join(duplicates[:10])
            )

        self._validate_numeric()

    # ---------------------------------------------------------

    def _validate_numeric(self) -> None:
        """
        Ensure every abundance value is numeric.
        """

        assert self.df is not None

        for column in self.sample_columns:

            try:

                self.df[column] = pd.to_numeric(self.df[column])

            except Exception:

                raise OTUTableError(
                    f"Column '{column}' contains " "non-numeric values."
                ) from None

        if (self.df[self.sample_columns] < 0).any().any():

            raise OTUTableError("Negative abundances detected.")

    # ---------------------------------------------------------

    @property
    def number_of_samples(self) -> int:

        return len(self.sample_columns)

    @property
    def number_of_otus(self) -> int:

        assert self.df is not None

        return len(self.df)

    # ---------------------------------------------------------

    def summary(self) -> None:

        print()

        print("=" * 60)
        print("OTU TABLE SUMMARY")
        print("=" * 60)

        print(f"Input file : {self.csv_file.name}")
        print(f"OTUs       : {self.number_of_otus:,}")
        print(f"Samples    : {self.number_of_samples}")

        print("=" * 60)

    # ---------------------------------------------------------

    def sequencing_depth(self) -> pd.Series:
        """
        Compute the total number of reads in every sample.

        Returns
        -------
        pandas.Series
            Index = sample names
            Values = sequencing depth
        """

        assert self.df is not None

        return self.df[self.sample_columns].sum(axis=0)

    # ---------------------------------------------------------

    def richness(self) -> pd.Series:
        """
        Compute observed richness.

        Richness = number of OTUs present (>0) in each sample.
        """

        assert self.df is not None

        return (self.df[self.sample_columns] > 0).sum(axis=0)

    # ---------------------------------------------------------

    def prevalence(self) -> pd.Series:
        """
        Compute prevalence of every OTU.

        Prevalence is the number of samples in which an OTU
        appears at least once.
        """

        assert self.df is not None

        return (self.df[self.sample_columns] > 0).sum(axis=1)

    # ---------------------------------------------------------

    def total_abundance(self) -> pd.Series:
        """
        Compute total abundance of every OTU.

        Returns
        -------
        pandas.Series
        """

        assert self.df is not None

        return self.df[self.sample_columns].sum(axis=1)

    # ---------------------------------------------------------

    def relative_abundance(self) -> pd.Series:
        """
        Compute relative abundance of every OTU across
        the complete experiment.

        Sum of returned values equals 1.0.
        """

        totals = self.total_abundance()

        grand_total = totals.sum()

        if grand_total == 0:

            raise OTUTableError("Total abundance is zero.")

        return totals / grand_total

    # ---------------------------------------------------------

    def top_otus(
        self,
        n: int = 20,
    ) -> pd.DataFrame:
        """
        Return the most abundant OTUs.

        Parameters
        ----------
        n
            Number of OTUs to return.
        """

        assert self.df is not None

        table = self.df.copy()

        table["TotalAbundance"] = self.total_abundance()

        return table.sort_values(
            "TotalAbundance",
            ascending=False,
        ).head(n)

    # ---------------------------------------------------------

    def filter_prevalence(
        self,
        minimum_samples: int,
    ) -> pd.DataFrame:
        """
        Remove rare OTUs.

        Parameters
        ----------
        minimum_samples
            Minimum number of samples in which an OTU
            must occur.
        """

        assert self.df is not None

        prevalence = self.prevalence()

        return self.df.loc[prevalence >= minimum_samples].copy()

    # ---------------------------------------------------------

    def sample_statistics(self) -> pd.DataFrame:
        """
        Produce a per-sample summary table.
        """

        depth = self.sequencing_depth()

        richness = self.richness()

        return pd.DataFrame(
            {
                "SequencingDepth": depth,
                "ObservedRichness": richness,
            }
        )

    # ---------------------------------------------------------

    def otu_statistics(self) -> pd.DataFrame:
        """
        Produce one summary row for every OTU.
        """

        assert self.df is not None

        table = pd.DataFrame()

        table["OTUID"] = self.df["OTUID"]

        table["TotalAbundance"] = self.total_abundance()

        table["RelativeAbundance"] = self.relative_abundance()

        table["Prevalence"] = self.prevalence()

        return table.sort_values(
            "TotalAbundance",
            ascending=False,
        )

    # ---------------------------------------------------------

    def report(self) -> None:
        """
        Print a concise report to the terminal.
        """

        depth = self.sequencing_depth()

        richness = self.richness()

        print()

        print("=" * 60)
        print("SEQUENCING DEPTH")
        print("=" * 60)

        print(depth.sort_values(ascending=False))

        print()

        print("=" * 60)
        print("OBSERVED RICHNESS")
        print("=" * 60)

        print(richness.sort_values(ascending=False))

        print()

        print("=" * 60)
        print("TOP 10 OTUs")
        print("=" * 60)

        print(
            self.top_otus(10)[
                [
                    "OTUID",
                    "TotalAbundance",
                ]
            ]
        )

    # ---------------------------------------------------------

    def export_sample_statistics(
        self,
        output: Path,
    ) -> None:
        """
        Export per-sample statistics.
        """

        table = self.sample_statistics()

        table.to_csv(
            output,
            index=True,
        )

    # ---------------------------------------------------------

    def export_otu_statistics(
        self,
        output: Path,
    ) -> None:
        """
        Export one row per OTU.
        """

        table = self.otu_statistics()

        table.to_csv(
            output,
            index=False,
        )

    # ---------------------------------------------------------

    def export_top_otus(
        self,
        output: Path,
        n: int,
    ) -> None:

        table = self.top_otus(n)

        table.to_csv(
            output,
            index=False,
        )

    # ---------------------------------------------------------

    def export_filtered_table(
        self,
        output: Path,
        minimum_prevalence: int,
    ) -> None:

        table = self.filter_prevalence(minimum_prevalence)

        table.to_csv(
            output,
            index=False,
        )


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=("Analyze microbial OTU abundance tables.")
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Input OTU table (.csv)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("results"),
        help=("Directory for exported reports."),
    )

    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top OTUs.",
    )

    parser.add_argument(
        "--minimum-prevalence",
        type=int,
        default=3,
        help="Minimum prevalence filter.",
    )

    return parser


def create_output_directory(
    directory: Path,
) -> None:

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )


def main() -> None:

    parser = build_parser()

    args = parser.parse_args()

    analyzer = OTUAnalyzer(args.input)

    try:

        analyzer.load()

        analyzer.summary()

        analyzer.report()

        create_output_directory(args.output)

        analyzer.export_sample_statistics(args.output / "sample_statistics.csv")

        analyzer.export_otu_statistics(args.output / "otu_statistics.csv")

        analyzer.export_top_otus(
            args.output / "top_otus.csv",
            args.top,
        )

        analyzer.export_filtered_table(
            args.output / "filtered_otus.csv",
            args.minimum_prevalence,
        )

    except (
        OTUTableError,
        FileNotFoundError,
    ) as error:

        sys.exit(str(error))

    print()

    print("=" * 60)
    print("Analysis completed successfully.")
    print("=" * 60)

    print()

    print("Generated files:")

    print(args.output / "sample_statistics.csv")

    print(args.output / "otu_statistics.csv")

    print(args.output / "top_otus.csv")

    print(args.output / "filtered_otus.csv")


if __name__ == "__main__":
    main()
