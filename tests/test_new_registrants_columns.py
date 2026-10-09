"""Tests for the per-person roster columns added in new_registrants 0.2.0.

Every participant here is invented; files are written to a temporary
folder.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import new_registrants

DAY_COL = "Which day would you prefer to attend?"
FORM_HEADER = ["Timestamp", "Email Address", "Full Name", DAY_COL]
CONTACT = ["+63-900-000-0000", "https://example.com/organiser"]


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    """Write rows to path as CSV and return the path."""
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


def read_roster(path: Path) -> list[dict[str, str]]:
    """Return the roster's rows as dictionaries."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def event(tmp_path: Path) -> Path:
    """Build an event folder: form, sent log, lookup and templates."""
    write_csv(tmp_path / "form.csv", [
        FORM_HEADER,
        ["10/1/2026 9:00:00", "sent.before@example.edu.ph",
         "Already Sent", "Day 1: Monday, 12 October"],
        ["10/2/2026 9:00:00", "ma.lorna@example.edu.ph",
         "Ma. Lorna B. Sample", "Day 1: Monday, 12 October"],
        ["10/3/2026 9:00:00", "pedro@example.edu.ph",
         "Pedro C. Testcase", "Day 2: Tuesday, 13 October"],
        ["10/4/2026 9:00:00", "pedro@example.edu.ph",
         "Pedro C. Testcase", "Day 3: Wednesday, 14 October"],
    ])
    (tmp_path / "sent.log").write_text("sent.before@example.edu.ph\n",
                                       encoding="utf-8")
    write_csv(tmp_path / "lookup.csv", [
        ["day", "workshop_day", "venue"],
        ["Day 1", "Monday, October 12", "Room A"],
        ["Day 2", "Tuesday, October 13", "Room A"],
        ["Day 3", "Wednesday, October 14", "Room B"],
    ])
    write_csv(tmp_path / "template.csv", [
        ["email", "certificate_name", "workshop_day", "contact_phone",
         "contact_messenger", "name", "venue"],
        ["old@example.edu.ph", "Old Person", "Monday, October 12",
         *CONTACT, "Old", "Room A"],
    ])
    write_csv(tmp_path / "contact_template.csv", [
        ["email", "contact_phone", "contact_messenger", "name"],
        ["old@example.edu.ph", *CONTACT, "Old Person"],
    ])
    return tmp_path


def run(event: Path, *extra: str, template: str = "template.csv",
        lookup: str | None = "lookup.csv") -> int:
    """Run main() against the event folder with the given extra options."""
    argv = [
        "--form", str(event / "form.csv"),
        "--sent-log", str(event / "sent.log"),
        "--template", str(event / template),
        "--roster", str(event / "roster.csv"),
        "--domain", "example.edu.ph",
        *extra,
    ]
    if lookup is not None:
        argv += ["--lookup", str(event / lookup), "--lookup-col", DAY_COL]
    return new_registrants.main(argv)


def test_fills_per_person_columns_in_template_order(event: Path) -> None:
    assert run(event, "--greeting", "first", "--write") == 0
    with (event / "roster.csv").open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == ["email", "certificate_name", "workshop_day",
                      "contact_phone", "contact_messenger", "name", "venue"]
    rows = {r["email"]: r for r in read_roster(event / "roster.csv")}
    assert set(rows) == {"ma.lorna@example.edu.ph", "pedro@example.edu.ph"}
    lorna = rows["ma.lorna@example.edu.ph"]
    assert lorna["name"] == "Ma. Lorna"
    assert lorna["certificate_name"] == "Ma. Lorna B. Sample"
    assert lorna["workshop_day"] == "Monday, October 12"
    assert lorna["venue"] == "Room A"
    assert [lorna["contact_phone"], lorna["contact_messenger"]] == CONTACT


def test_later_row_supplies_the_looked_up_answer(event: Path) -> None:
    """An edited or repeated response moves the registrant's day."""
    assert run(event, "--write") == 0
    rows = {r["email"]: r for r in read_roster(event / "roster.csv")}
    pedro = rows["pedro@example.edu.ph"]
    assert pedro["workshop_day"] == "Wednesday, October 14"
    assert pedro["venue"] == "Room B"


def test_default_greeting_keeps_the_full_name(event: Path) -> None:
    """Without --greeting, 'name' holds the full name, as in 0.1.0."""
    assert run(event, "--write", template="contact_template.csv",
               lookup=None) == 0
    names = {r["name"] for r in read_roster(event / "roster.csv")}
    assert names == {"Ma. Lorna B. Sample", "Pedro C. Testcase"}


def test_unmatched_answer_blocks_write(event: Path) -> None:
    write_csv(event / "short.csv", [
        ["day", "workshop_day", "venue"],
        ["Day 1", "Monday, October 12", "Room A"],
    ])
    assert run(event, "--write", lookup="short.csv") == 1
    assert not (event / "roster.csv").exists()


def test_per_person_column_without_lookup_is_refused(event: Path) -> None:
    assert run(event, "--write", lookup=None) == 2
    assert not (event / "roster.csv").exists()


@pytest.mark.parametrize("bad_rows", [
    [["Day 1", "Monday, October 12", "Room A"],
     ["Day 1", "Tuesday, October 13", "Room A"]],
    [["Day 1", "Monday, October 12", ""]],
], ids=["repeated key", "blank value"])
def test_malformed_lookup_is_refused(event: Path,
                                     bad_rows: list[list[str]]) -> None:
    write_csv(event / "bad.csv", [["day", "workshop_day", "venue"],
                                  *bad_rows])
    assert run(event, "--write", lookup="bad.csv") == 2
    assert not (event / "roster.csv").exists()


def test_lookup_needs_its_column(event: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        new_registrants.main([
            "--form", str(event / "form.csv"),
            "--sent-log", str(event / "sent.log"),
            "--template", str(event / "template.csv"),
            "--roster", str(event / "roster.csv"),
            "--lookup", str(event / "lookup.csv"),
        ])
    assert exc.value.code == 2
