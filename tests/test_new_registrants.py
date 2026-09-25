"""Regression tests for new_registrants.py.

Run from the repository root with ``python -m pytest``. Every name and
address here is invented; no real registration data belongs in this
repository.
"""

import csv
from pathlib import Path

import pytest

import new_registrants

FORM_HEADER = ["Timestamp", "Email Address", "Full Name", "College"]
ROSTER_HEADER = ["email", "name", "contact_phone", "contact_messenger"]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def event(tmp_path, monkeypatch):
    """An event folder: three sent, one excluded, two new, one blank."""
    monkeypatch.chdir(tmp_path)
    write_csv(Path("form.csv"), FORM_HEADER, [
        ["9/24/2026 8:00:00", "ana.cruz@example.edu", "Ana B. Cruz", "A"],
        ["9/24/2026 9:00:00", "ben.diaz@example.edu", "Ben C. Diaz", "A"],
        ["", "", "", ""],
        ["9/25/2026 7:00:00", "cy.eng@example.edu", "Cy D. Eng", "A"],
        ["9/25/2026 8:00:00", "dee.fox@example.edu", "Dee E. Fox", "A"],
        ["9/25/2026 9:00:00", "eli.go@example.edu", "ELI F. GO", "A"],
        ["9/25/2026 9:30:00", "fay.hu@gmail.com", "Fay G. Hu", "A"],
    ])
    Path("logs").mkdir()
    Path("logs/first.log").write_text(
        "ana.cruz@example.edu\nben.diaz@example.edu\n", encoding="utf-8")
    Path("second.sent.log").write_text(
        "CY.ENG@example.edu\n", encoding="utf-8")
    Path("exclusions.txt").write_text(
        "dee.fox@example.edu  # has the steps already\n", encoding="utf-8")
    Path("rosters").mkdir()
    write_csv(Path("rosters/v2.csv"), ROSTER_HEADER, [
        ["cy.eng@example.edu", "Cy D. Eng", "+00-000", "https://m.me/x"],
    ])
    return tmp_path


def run(*extra: str) -> int:
    return new_registrants.main([
        "--form", "form.csv",
        "--sent-log", "logs/first.log", "second.sent.log",
        "--exclude", "exclusions.txt",
        "--template", "rosters/v2.csv",
        "--roster", "rosters/v3.csv",
        "--domain", "example.edu",
        *extra,
    ])


def roster_rows() -> list[dict[str, str]]:
    with Path("rosters/v3.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_report_only_writes_nothing(event, capsys):
    assert run() == 0
    assert "new: 2" in capsys.readouterr().out
    assert not Path("rosters/v3.csv").exists()


def test_write_adds_only_new_people_verbatim(event):
    assert run("--write") == 0
    rows = roster_rows()
    assert [r["email"] for r in rows] == [
        "eli.go@example.edu", "fay.hu@gmail.com"]
    assert rows[0]["name"] == "ELI F. GO"  # flagged, never "corrected"
    assert rows[0]["contact_phone"] == "+00-000"
    assert "\r" not in Path("rosters/v3.csv").read_text(encoding="utf-8")


def test_rerun_adds_nobody_twice(event, capsys):
    run("--write")
    capsys.readouterr()
    assert run("--write") == 0
    assert "new: 0" in capsys.readouterr().out
    assert len(roster_rows()) == 2


def test_later_registration_adds_one_and_later_name_wins(event):
    run("--write")
    with Path("form.csv").open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["9/25/2026 10:00:00", "gus.ivy@example.edu",
                         "Gus H. Ivi", "A"])
        writer.writerow(["9/25/2026 10:05:00", "Gus.Ivy@example.edu",
                         "Gus H. Ivy", "A"])
    assert run("--write") == 0
    rows = roster_rows()
    assert len(rows) == 3
    assert rows[-1]["name"] == "Gus H. Ivy"


def test_log_in_another_format_stops_the_run(event, capsys):
    Path("logs/first.log").write_text(
        "2026-09-24 08:00 sent ana.cruz@example.edu\n", encoding="utf-8")
    assert run("--write") == 2
    assert "line 1 is not a bare address" in capsys.readouterr().err
    assert not Path("rosters/v3.csv").exists()


def test_missing_input_is_an_error_not_a_traceback(event, capsys):
    Path("form.csv").unlink()
    assert run() == 2
    assert "not found: form.csv" in capsys.readouterr().err


def test_wrong_log_blocks_write(event, capsys):
    Path("logs/first.log").write_text(
        "someone.else@example.edu\n", encoding="utf-8")
    assert run("--write") == 1
    assert "matches nobody" in capsys.readouterr().err
    assert not Path("rosters/v3.csv").exists()


def test_per_person_template_column_is_refused(event, capsys):
    write_csv(Path("rosters/v2.csv"), ROSTER_HEADER + ["college"], [
        ["cy.eng@example.edu", "Cy D. Eng", "+00-000", "x", "A"],
    ])
    assert run() == 2
    assert "cannot fill" in capsys.readouterr().err


def test_invalid_new_address_blocks_write(event, capsys):
    with Path("form.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["9/25/2026 11:00:00", "", "No Address", "A"])
    assert run("--write") == 1
    assert "invalid address" in capsys.readouterr().err
    assert not Path("rosters/v3.csv").exists()
