"""Regression tests for mail_merge.py.

Run with ``pytest`` or ``python -m pytest``; pyproject.toml puts the
repository root on sys.path so ``import mail_merge`` resolves either way. No email is sent: SMTP_SSL is
replaced by a fake that records messages.
"""

import json
import smtplib
import sys
from pathlib import Path

import pytest

import mail_merge


class FakeSMTP:
    """Stand-in for smtplib.SMTP_SSL that records instead of sending."""

    sent: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, *args):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Return a function that runs mail_merge.main() with the given args."""
    FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("WORKSHOP_EMAIL", "me@example.com")
    monkeypatch.setenv("WORKSHOP_PASSWORD", "x")
    monkeypatch.chdir(tmp_path)

    def _run(*args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["mail_merge.py", *args])
        mail_merge.main()

    return _run


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


ROSTER = "email,Name\na@example.com,Ana\nb@example.com,Ben\n"


# --- Fix 1: the dry run must fill the template, not only name-check it ----


@pytest.mark.parametrize(
    "roster, template",
    [
        (ROSTER, "Hello {}!\n"),
        (
            '"email","Full name (e.g. Juan Dela Cruz)"\na@example.com,Ana Reyes\n',
            "Hi {Full name (e.g. Juan Dela Cruz)}\n",
        ),
    ],
    ids=["empty-braces", "dotted-google-forms-header"],
)
def test_dry_run_rejects_unfillable_template(run, tmp_path, roster, template):
    write(tmp_path / "r.csv", roster)
    write(tmp_path / "body.txt", template)
    with pytest.raises(SystemExit) as exc:
        run("-R", "r.csv", "-b", "body.txt", "--dry-run")
    assert "cannot be filled" in str(exc.value)
    assert FakeSMTP.sent == []


def test_real_send_of_bad_template_exits_cleanly_before_sending(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hello {}!\n")
    with pytest.raises(SystemExit):
        run("-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y")
    assert FakeSMTP.sent == []
    assert not (tmp_path / "s.log").exists()


# --- Fix 2: a lone brace gets the readable message, not a traceback ------


def test_lone_brace_exits_with_readable_message(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hello {Name}\nif (ok) {{ print(1)\n}\n")
    with pytest.raises(SystemExit) as exc:
        run("-R", "r.csv", "-b", "body.txt", "--dry-run")
    assert "must be doubled" in str(exc.value)


# --- Fix 3: skipped_prior counts roster rows, not lines in the log --------


def test_skipped_prior_counts_roster_rows_not_log_lines(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hi {Name}\n")
    # Log: one address from this roster plus three that are not in it.
    write(
        tmp_path / "s.log",
        "a@example.com\nzz1@example.com\nzz2@example.com\nzz3@example.com\n",
    )
    run(
        "-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log",
        "--manifest", "m.jsonl", "--campaign-id", "t-2026-09-24", "-y",
    )
    record = json.loads((tmp_path / "m.jsonl").read_text(encoding="utf-8"))
    assert record["sent_this_run"] == 1
    assert record["skipped_prior"] == 1


# --- Behaviour that must NOT change ---------------------------------------


def test_numbered_placeholder_still_rejected_as_unknown_column(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hello {0}!\n")
    with pytest.raises(SystemExit) as exc:
        run("-R", "r.csv", "-b", "body.txt", "--dry-run")
    assert "unknown placeholder" in str(exc.value)


def test_valid_template_with_doubled_braces_sends_rendered_body(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hi {Name}\nf <- function(x) {{ x + 1 }}\n")
    run("-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y")
    bodies = [m.get_content() for m in FakeSMTP.sent]
    assert bodies == [
        "Hi Ana\nf <- function(x) { x + 1 }\n",
        "Hi Ben\nf <- function(x) { x + 1 }\n",
    ]
    assert (tmp_path / "s.log").read_text() == "a@example.com\nb@example.com\n"


# --- Fix 4: --copy-to takes several addresses, by repetition or commas ---


def copy_messages():
    """Return the summary copies among the recorded messages."""
    return [m for m in FakeSMTP.sent if m["Subject"].startswith("[Copy]")]


@pytest.mark.parametrize(
    "flags",
    [
        ["--copy-to", "lead@example.org", "--copy-to", "host@example.org"],
        ["--copy-to", "lead@example.org,host@example.org"],
        ["--copy-to", "lead@example.org, host@example.org", "--copy-to", "LEAD@example.org"],
    ],
    ids=["repeated", "comma-separated", "mixed-with-duplicate"],
)
def test_copy_to_reaches_every_address_once(run, tmp_path, flags):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hi {Name}\n")
    run("-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y", *flags)
    copies = copy_messages()
    assert len(copies) == 1
    assert copies[0]["To"] == "lead@example.org, host@example.org"
    assert len(FakeSMTP.sent) == 3  # two recipients plus one copy


# --- Fix 5: the manifest records who received copies ---------------------


def test_manifest_records_copy_recipients(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hi {Name}\n")
    run(
        "-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y",
        "--manifest", "m.jsonl", "--campaign-id", "copy-2026-10-04",
        "--copy-to", "lead@example.org,host@example.org",
        "--cc", "archive@example.org",
    )
    record = json.loads((tmp_path / "m.jsonl").read_text(encoding="utf-8"))
    assert record["copy_to"] == ["lead@example.org", "host@example.org"]
    assert record["cc"] == ["archive@example.org"]
    assert "bcc" not in record  # absent when unused, like other optional fields


# --- Fix 6: addresses get the shared roster_checks rules ------------------


@pytest.mark.parametrize(
    "address, reason",
    [
        ("ana@gmail.con", "typo of ...@gmail.com"),
        ("@example.com", "malformed"),
        ("ana@localhost", "malformed"),
        ("ana@example..com", "malformed"),
    ],
    ids=["typo-domain", "no-local-part", "dotless-domain", "empty-label"],
)
def test_roster_address_rejected_before_sending(run, tmp_path, address, reason):
    write(tmp_path / "r.csv", f"email,Name\nok@example.com,Ok\n{address},Bad\n")
    write(tmp_path / "body.txt", "Hi {Name}\n")
    with pytest.raises(SystemExit) as exc:
        run("-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y")
    assert reason in str(exc.value)
    assert FakeSMTP.sent == []
    assert not (tmp_path / "s.log").exists()


def test_real_provider_near_gmail_is_accepted(run, tmp_path):
    write(tmp_path / "r.csv", "email,Name\nana@ymail.com,Ana\nben@mail.com,Ben\n")
    write(tmp_path / "body.txt", "Hi {Name}\n")
    run("-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y")
    assert len(FakeSMTP.sent) == 2


def test_bad_copy_address_rejected_before_sending(run, tmp_path):
    write(tmp_path / "r.csv", ROSTER)
    write(tmp_path / "body.txt", "Hi {Name}\n")
    with pytest.raises(SystemExit) as exc:
        run(
            "-R", "r.csv", "-b", "body.txt", "--sent-log", "s.log", "-y",
            "--copy-to", "lead@example.org,host@gmial.com",
        )
    assert "--copy-to 'host@gmial.com'" in str(exc.value)
    assert FakeSMTP.sent == []
