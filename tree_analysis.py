#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""
tree_analysis.py

Inspect, query, and export information from
phylogenetic trees stored in Newick format.

Features
--------
• Display summary statistics
• Search for taxa
• Find a specific taxon
• Compute branch distances
• Find the most recent common ancestor
• Count descendants beneath a clade
• Render trees or subtrees as ASCII
• Export terminal taxa
• Export summary statistics

Examples
--------
Display tree statistics

    python3 tree_analysis.py soil.tree.nwk --summary

Show the first 20 terminal taxa

    python3 tree_analysis.py soil.tree.nwk --head 20

Search for taxa containing a string

    python3 tree_analysis.py soil.tree.nwk --search OTU

Find a particular taxon

    python3 tree_analysis.py soil.tree.nwk --find 151811

Compute branch distance

    python3 tree_analysis.py soil.tree.nwk \
        --distance 707761 418158

Find the most recent common ancestor

    python3 tree_analysis.py soil.tree.nwk \
        --ancestor 707761 418158

Count descendants beneath a clade

    python3 tree_analysis.py soil.tree.nwk \
        --descendants 151811

Render a small tree

    python3 tree_analysis.py soil.tree.nwk --draw

Render a subtree

    python3 tree_analysis.py soil.tree.nwk \
        --draw-subtree 151811

Export terminal taxa

    python3 tree_analysis.py soil.tree.nwk \
        --export-tips terminal_taxa.txt

Export summary statistics

    python3 tree_analysis.py soil.tree.nwk \
        --export-summary summary.txt

Notes
-----
This script analyzes only the phylogenetic tree.

Tree tip names are taken directly from the Newick file.
Depending on how the tree was generated, these may be
Feature IDs, OTU IDs, ASV IDs, accession numbers, or
other identifiers—not taxonomic names.

To query taxa such as "Bacillus" or "Proteobacteria",
use the corresponding taxonomy table (e.g. soil.tax.csv)
to identify the associated Feature IDs first.

Author
------
Jan Ephraim R. Vallente
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

from Bio import Phylo
from Bio.Phylo.BaseTree import Clade
from Bio.Phylo.BaseTree import Tree


class TreeAnalysisError(ValueError):
    """Raised when a phylogenetic tree is malformed."""


class TreeAnalyzer:
    """
    Utility class for inspecting
    phylogenetic trees.
    """

    def __init__(
        self,
        tree_file: Path,
    ) -> None:

        self.tree_file = tree_file

        self.tree: Tree | None = None

        # Built once after loading the tree.
        # Maps taxon names to their corresponding Clade.
        self._name_index: dict[str, Clade] = {}

    # -----------------------------------------------------

    def load_tree(self) -> None:
        """
        Read a Newick tree.
        """

        try:

            self.tree = Phylo.read(
                self.tree_file,
                "newick",
            )

        except FileNotFoundError:

            raise FileNotFoundError(
                f"Cannot locate tree:\n" f"{self.tree_file}"
            ) from None

        except ValueError:

            raise TreeAnalysisError("The file is not a valid Newick tree.") from None

        self._validate()
        self._build_index()

    # -----------------------------------------------------

    def _validate(self) -> None:

        assert self.tree is not None

        if not self.tree.get_terminals():

            raise TreeAnalysisError("Tree contains no terminal taxa.")

        if self.tree.root is None:

            raise TreeAnalysisError("Tree has no root.")

    # -----------------------------------------------------

    def summary(self) -> dict[str, int | float | bool]:
        """
        Compute basic statistics about the tree.

        Returns
        -------
        dict
            Dictionary containing summary information.
        """

        assert self.tree is not None

        terminals = self.tree.get_terminals()
        internal = self.tree.get_nonterminals()

        total_branch_length = self.tree.total_branch_length()

        depths = self.tree.depths()

        max_depth = max(depths.values(), default=0.0)

        bifurcating = 0
        multifurcating = 0

        for node in internal:

            children = len(node.clades)

            if children == 2:
                bifurcating += 1

            elif children > 2:
                multifurcating += 1

        return {
            "tips": len(terminals),
            "internal_nodes": len(internal),
            "rooted": self.tree.rooted,
            "total_branch_length": total_branch_length,
            "maximum_depth": max_depth,
            "bifurcating_nodes": bifurcating,
            "multifurcating_nodes": multifurcating,
        }

    # -----------------------------------------------------

    def print_summary(self) -> None:

        summary = self.summary()

        print("\n========== TREE SUMMARY ==========")

        print(f"Tips:                 {summary['tips']:,}")

        print(f"Internal Nodes:       " f"{summary['internal_nodes']:,}")

        print(f"Rooted:               " f"{summary['rooted']}")

        print(f"Total Branch Length:  " f"{summary['total_branch_length']:.6f}")

        print(f"Maximum Depth:        " f"{summary['maximum_depth']:.6f}")

        print(f"Bifurcating Nodes:    " f"{summary['bifurcating_nodes']:,}")

        print(f"Multifurcating Nodes: " f"{summary['multifurcating_nodes']:,}")

        print("=" * 34)

    # -----------------------------------------------------
    def _build_index(self) -> None:
        """
        Build a lookup table from taxon names
        to Clade objects.
        """

        assert self.tree is not None

        self._name_index.clear()

        for clade in self.tree.find_clades():

            if clade.name is None:
                continue

            self._name_index[clade.name] = clade

    #  -----------------------------------------------------
    def find_taxon(
        self,
        name: str,
    ) -> Clade:
        """
        Return the clade associated with a taxon name.

        Raises
        ------
        ValueError
            If the taxon is not present in the tree.
        """

        assert self.tree is not None

        try:
            return self._name_index[name]

        except KeyError:
            raise ValueError(f"Taxon '{name}' was not found.") from None

    # -----------------------------------------------------

    def search_taxa(
        self,
        query: str,
    ) -> list[str]:
        """
        Return every taxon whose name contains
        the supplied query string.
        """

        assert self.tree is not None

        query = query.casefold()

        matches = []

        for clade in self.tree.get_terminals():

            if clade.name is None:
                continue

            if query in clade.name.casefold():
                matches.append(clade.name)

        return matches

    # -----------------------------------------------------

    def terminal_names(self) -> Iterator[str]:
        """
        Yield terminal taxon names.
        """

        assert self.tree is not None

        for clade in self.tree.get_terminals():

            if clade.name is not None:
                yield clade.name

    # -----------------------------------------------------

    def common_ancestor(
        self,
        taxon1: str,
        taxon2: str,
    ) -> Clade:
        """
        Return the most recent common ancestor
        of two taxa.
        """

        assert self.tree is not None

        return self.tree.common_ancestor(
            taxon1,
            taxon2,
        )

    # -----------------------------------------------------

    def distance(
        self,
        taxon1: str,
        taxon2: str,
    ) -> float:
        """
        Return branch distance
        between two taxa.
        """

        assert self.tree is not None

        return self.tree.distance(
            taxon1,
            taxon2,
        )

    # -----------------------------------------------------

    def descendant_count(
        self,
        taxon: str,
    ) -> int:
        """
        Count descendant leaves beneath
        the specified clade.
        """

        clade = self.find_taxon(taxon)

        return len(clade.get_terminals())

    # -----------------------------------------------------

    def draw_ascii(
        self,
        max_tips: int = 50,
    ) -> None:
        """
        Draw the tree as ASCII art.

        Extremely large trees are refused because the
        output would overwhelm the terminal.
        """

        assert self.tree is not None

        tips = len(self.tree.get_terminals())

        if tips > max_tips:
            raise TreeAnalysisError(
                "ASCII rendering refused.\n"
                f"The tree contains {tips:,} terminal taxa.\n"
                "Extract a subtree first."
            )

        Phylo.draw_ascii(self.tree)

    # -----------------------------------------------------

    def extract_subtree(
        self,
        taxon: str,
    ) -> Tree:
        """
        Return the subtree rooted at the
        specified taxon.
        """

        clade = self.find_taxon(taxon)

        return Tree(
            root=clade,
            rooted=self.tree.rooted,
        )

    # -----------------------------------------------------

    def draw_subtree(
        self,
        taxon: str,
    ) -> None:
        """
        Draw a subtree rooted at
        the requested taxon.
        """

        subtree = self.extract_subtree(
            taxon,
        )

        Phylo.draw_ascii(subtree)

    # -----------------------------------------------------

    def export_terminal_names(
        self,
        output: Path,
    ) -> None:
        """
        Export terminal taxa to a text file.
        """

        with output.open(
            "w",
            encoding="utf-8",
        ) as file:

            for name in self.terminal_names():

                file.write(f"{name}\n")

    # -----------------------------------------------------

    def export_summary(
        self,
        output: Path,
    ) -> None:
        """
        Export summary statistics.
        """

        summary = self.summary()

        with output.open(
            "w",
            encoding="utf-8",
        ) as file:

            file.write("========== TREE SUMMARY ==========\n")

            file.write(f"Tips: {summary['tips']:,}\n")

            file.write(f"Internal Nodes: " f"{summary['internal_nodes']:,}\n")

            file.write(f"Rooted: " f"{summary['rooted']}\n")

            file.write(
                f"Total Branch Length: " f"{summary['total_branch_length']:.6f}\n"
            )

            file.write(f"Maximum Depth: " f"{summary['maximum_depth']:.6f}\n")

            file.write(f"Bifurcating Nodes: " f"{summary['bifurcating_nodes']:,}\n")

            file.write(
                f"Multifurcating Nodes: " f"{summary['multifurcating_nodes']:,}\n"
            )


def flags() -> argparse.ArgumentParser:
    """
    Configure command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=("Inspect and query phylogenetic trees " "stored in Newick format.")
    )

    parser.add_argument(
        "tree",
        type=Path,
        help="Input Newick tree.",
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help="Display summary statistics.",
    )

    parser.add_argument(
        "--head",
        type=int,
        metavar="N",
        help="Show the first N terminal taxa.",
    )

    parser.add_argument(
        "--draw",
        action="store_true",
        help=("Render the entire tree as ASCII " "(small trees only)."),
    )

    parser.add_argument(
        "--find",
        metavar="TAXON",
        help="Find a taxon by its name.",
    )

    parser.add_argument(
        "--search",
        metavar="TEXT",
        help="Search taxon names containing TEXT.",
    )

    parser.add_argument(
        "--distance",
        nargs=2,
        metavar=("TAXON1", "TAXON2"),
        help="Compute branch distance between two taxa.",
    )

    parser.add_argument(
        "--ancestor",
        nargs=2,
        metavar=("TAXON1", "TAXON2"),
        help="Find the most recent common ancestor.",
    )

    parser.add_argument(
        "--descendants",
        metavar="TAXON",
        help="Count descendant terminal taxa.",
    )

    parser.add_argument(
        "--draw-subtree",
        metavar="TAXON",
        help="Render the subtree rooted at TAXON.",
    )

    parser.add_argument(
        "--export-summary",
        type=Path,
        metavar="FILE",
        help="Write tree summary to a text file.",
    )

    parser.add_argument(
        "--export-tips",
        type=Path,
        metavar="FILE",
        help="Export all terminal taxa.",
    )

    return parser


def main() -> None:

    parser = flags()

    args = parser.parse_args()

    actions = (
        args.summary,
        args.head is not None,
        args.draw,
        args.find is not None,
        args.search is not None,
        args.distance is not None,
        args.ancestor is not None,
        args.descendants is not None,
        args.draw_subtree is not None,
        args.export_summary is not None,
        args.export_tips is not None,
    )

    if sum(actions) != 1:
        parser.error("Choose exactly one action.")

    analyzer = TreeAnalyzer(args.tree)

    try:
        analyzer.load_tree()

        if args.summary:
            analyzer.print_summary()

        elif args.draw:
            analyzer.draw_ascii()

        elif args.find:

            clade = analyzer.find_taxon(
                args.find,
            )

            print(clade)

        elif args.search:

            matches = analyzer.search_taxa(
                args.search,
            )

            for name in matches:
                print(name)

            print(f"\nMatches: {len(matches):,}")

        elif args.distance:

            taxon1, taxon2 = args.distance

            distance = analyzer.distance(
                taxon1,
                taxon2,
            )

            print(
                f"Branch distance between "
                f"'{taxon1}' and '{taxon2}': "
                f"{distance:.7f}"
            )

        elif args.ancestor:

            taxon1, taxon2 = args.ancestor

            print(
                analyzer.common_ancestor(
                    taxon1,
                    taxon2,
                )
            )

        elif args.descendants:

            print(
                analyzer.descendant_count(
                    args.descendants,
                )
            )

        elif args.draw_subtree:

            analyzer.draw_subtree(
                args.draw_subtree,
            )

        elif args.export_summary:

            analyzer.export_summary(
                args.export_summary,
            )

            print("Summary exported successfully.")

        elif args.export_tips:

            analyzer.export_terminal_names(
                args.export_tips,
            )

            print("Terminal taxa exported successfully.")

        elif args.head:

            for i, name in enumerate(analyzer.terminal_names(), start=1):

                print(name)

                if i >= args.head:
                    break
    except (
        FileNotFoundError,
        TreeAnalysisError,
        ValueError,
    ) as e:

        sys.exit(str(e))


if __name__ == "__main__":
    main()
