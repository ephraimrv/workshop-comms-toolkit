r"""Send personalised bulk email with per-recipient attachments and templating.

This module reads a CSV or TSV roster, validates the input, attaches both
per-recipient and shared files, fills a message template from any column
in the roster, and sends one email per recipient using SMTP.

Features
--------
* Supports CSV and TSV rosters.
* Validates required columns and email addresses.
* Supports zero, one, or many per-recipient attachments
  (semicolon-separated in the roster).
* Supports one or more shared attachments sent to every recipient.
* Supports custom attachment display names independent of the filenames
  stored on disk.
* Verifies that all attachment files exist before sending.
* Fills message templates from any roster column, e.g. ``{Name}``,
  ``{Department}``, or ``{Organisation}``.
* Dry-run mode for validation without sending email.
* Automatically skips recipients recorded in ``sent.log``.
* Requires interactive confirmation before a real send
  (skip with ``--yes``).
* Uses SSL by default for secure SMTP communication.

Environment Variables
---------------------
WORKSHOP_EMAIL
    SMTP account used to send email.

WORKSHOP_PASSWORD
    SMTP password or Gmail App Password.

Examples
--------
Preview the mailing without sending anything::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        -b body.txt \
        --dry-run

Send personalised emails from a body template::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        -b body.txt \
        -s "Workshop Materials"

Send a personalised message written directly on the command line::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        -m "Hello {Name}, thank you for attending."

Attach one certificate per participant::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        --attachment-dir certificates \
        -b body.txt

Attach each participant's certificate plus a shared handout::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        --attachment-dir certificates \
        --attach Workshop-Handout.pdf \
        -b body.txt

Use friendly attachment names while keeping safe filenames on disk::

    python mail_merge.py \
        -R participants.csv \
        --email-col Username \
        --attachment-dir certificates \
        --attachment-name-col attachment_display \
        -b body.txt
"""

__author__ = "Jan Ephraim R. Vallente"
__version__ = "1.1.0"

import argparse
import csv
import mimetypes
import os
import smtplib
import ssl
import string
import sys
import textwrap
import time
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def guess_mime(path: Path) -> Tuple[str, str]:
    """Return (maintype, subtype); unknown or encoded types fall back safely."""
    mime_type, encoding = mimetypes.guess_type(path)
    if mime_type is None or encoding is not None:
        return "application", "octet-stream"
    maintype, _, subtype = mime_type.partition("/")
    return maintype, subtype


def referenced_placeholders(template: str) -> Set[str]:
    """Return every {field} name the template actually references."""
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }


def parse_attachment_list(raw: str, sep: str) -> List[str]:
    """Split a roster cell into a clean list of filenames; drop empty entries."""
    return [part.strip() for part in raw.split(sep) if part.strip()]


EXTRA_FIELDS = "__extra__"
MISSING_FIELD = "__missing__"


def load_roster(roster: Path, email_col: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read the roster, reporting every malformed row at once.

    utf-8-sig strips the BOM Google Sheets writes. Rows with too many or too
    few fields are collected and reported together, so a large roster can be
    corrected in one pass rather than one error per re-run.
    """
    delimiter = "\t" if roster.suffix.lower() in {".tsv", ".tab"} else ","
    problems: List[str] = []
    rows: List[Dict[str, str]] = []

    with roster.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(
            f,
            delimiter=delimiter,
            restkey=EXTRA_FIELDS,
            restval=MISSING_FIELD,
        )
        if reader.fieldnames is None:
            raise ValueError(f"{roster} appears to be empty.")
        headers = [h.strip() for h in reader.fieldnames]
        if email_col not in headers:
            raise ValueError(f"Column {email_col!r} not found. Available: {headers}")

        for lineno, raw in enumerate(reader, start=2):
            if EXTRA_FIELDS in raw:
                extra = raw.pop(EXTRA_FIELDS)
                problems.append(
                    f"  line {lineno}: too many fields "
                    f"(expected {len(headers)}). Leftover: {extra!r}. "
                    f"A value containing a comma needs double quotes around it."
                )
                continue

            short = [k for k, v in raw.items() if v == MISSING_FIELD]
            if short:
                problems.append(
                    f"  line {lineno}: too few fields "
                    f"(expected {len(headers)}). Empty: {short}."
                )
                continue

            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            addr = parseaddr(row[email_col])[1]
            if "@" not in addr:
                problems.append(f"  line {lineno}: invalid email {row[email_col]!r}")
                continue
            row[email_col] = addr
            rows.append(row)

    if problems:
        raise ValueError(
            f"{roster} has {len(problems)} malformed row(s):\n"
            + "\n".join(problems)
            + "\n\nTip: edit rosters in a spreadsheet and export to CSV; "
            "spreadsheets quote embedded commas automatically."
        )
    return rows, headers


def build_message(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: List[Path],
    display_names: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
) -> EmailMessage:
    """Build one message with zero or more attachments for one recipient.

    display_names, when given, sets the filename each attachment appears
    under in the recipient's mail client. Non-ASCII names are encoded per
    RFC 2231 by the email package, so accented names are safe here even
    though they would be unsafe as filesystem paths.
    """
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg.set_content(body)
    names = display_names or [p.name for p in attachments]
    for path, shown in zip(attachments, names):
        maintype, subtype = guess_mime(path)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=shown,
        )
    return msg


COPY_PREAMBLE = (
    "This is a copy of a message sent to {count} recipient(s) as part of the "
    "campaign below. It is sent once, not once per recipient.\n"
    "\n"
    "Placeholders such as {{Name}} were substituted individually for each "
    "recipient; the template is reproduced verbatim below.\n"
    "\n"
    "{rule}\n"
    "\n"
)


def build_copy_message(
    sender: str,
    recipient: str,
    subject: str,
    template: str,
    shared_attachments: List[Path],
    count: int,
) -> EmailMessage:
    """Build the single summary copy sent to --copy-to.

    The unrendered template is sent rather than any one recipient's version,
    because no single rendering represents the campaign. Only shared
    attachments are included; per-recipient files differ by definition.
    """
    preamble = COPY_PREAMBLE.format(count=count, rule="-" * 60)
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"[Copy] {subject}"
    msg.set_content(preamble + template)
    for path in shared_attachments:
        maintype, subtype = guess_mime(path)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return msg


def parse_args() -> argparse.Namespace:
    """Build and parse the command-line interface."""
    p = argparse.ArgumentParser(
        prog="mail_merge.py",
        description=(
            "Send one personalised email per roster row, with per-recipient "
            "attachments and {column} placeholders drawn from the roster."
        ),
        epilog=textwrap.dedent("""\
            Examples:

              Preview without sending (always do this first):
                  mail_merge.py -R roster.csv --email-col Username \\
                      -b body.txt --dry-run

              Plain personalised email:
                  mail_merge.py -R roster.csv --email-col Username \\
                      -m "Hello {Name}, see you Thursday."

              Per-recipient certificate plus a handout for everyone:
                  mail_merge.py -R roster.csv --email-col Username \\
                      --attachment-dir certs --attach handout.pdf -b body.txt

            Notes:
              Placeholders match roster column headers exactly, e.g. {Name}.
              To include a literal brace in the body, double it: {{ or }}.
              Interrupted runs resume safely; addresses already in the sent
              log are skipped.
            """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "-R",
        "--roster",
        type=Path,
        required=True,
        metavar="FILE",
        help="CSV/TSV roster exported from the responses sheet. "
        "Delimiter is inferred from the file extension.",
    )
    p.add_argument(
        "--email-col",
        default="email",
        metavar="COLUMN",
        help="Roster column holding the recipient address " "(default: %(default)s).",
    )
    p.add_argument(
        "--attachment-col",
        default="attachments",
        metavar="COLUMN",
        help="Roster column listing this recipient's own file(s). "
        "Ignored if the column is absent "
        "(default: %(default)s).",
    )
    p.add_argument(
        "--attachment-sep",
        default=";",
        metavar="CHAR",
        help="Separator between several filenames in one cell "
        "(default: %(default)r).",
    )
    p.add_argument(
        "--attachment-dir",
        type=Path,
        default=Path("."),
        metavar="DIRECTORY",
        help="Directory holding the attachment files. Filenames "
        "from the roster are resolved relative to this "
        "(default: current directory).",
    )
    p.add_argument(
        "--attachment-name-col",
        default=None,
        metavar="COLUMN",
        help="Roster column giving the filename each attachment "
        "should appear as IN THE EMAIL, separated by "
        "--attachment-sep. Lets files be stored on disk under "
        "safe ASCII serials while recipients see readable "
        "names. Must have one entry per attachment.",
    )
    p.add_argument(
        "--attach",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="File attached to EVERY recipient, in addition to "
        "their own. Repeat the flag for several files. "
        "Resolved as given, not relative to --attachment-dir.",
    )

    p.add_argument(
        "--cc",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="Address carbon-copied on EVERY message. A 61-recipient "
        "campaign therefore sends this address 61 emails. Correct "
        "for an archive mailbox; for a single copy of the campaign "
        "use --copy-to. Repeat the flag for several addresses.",
    )
    p.add_argument(
        "--bcc",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="As --cc, but hidden from recipients. Still one email per "
        "recipient. Repeat the flag for several addresses.",
    )
    p.add_argument(
        "--copy-to",
        default=None,
        metavar="ADDRESS",
        help="Send ONE copy of the campaign to this address after the "
        "run, containing the unrendered body template, the recipient "
        "count and any shared attachments. This is the flag to use "
        "when a supervisor wants a record of what went out.",
    )

    p.add_argument(
        "-s",
        "--subject",
        default="Workshop Materials",
        metavar="TEXT",
        help="Subject line (default: %(default)r). Placeholders "
        "are not substituted here.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "-m",
        "--message",
        metavar="TEXT",
        help="Body text given inline. Best for short messages.",
    )
    g.add_argument(
        "-b",
        "--body-file",
        type=Path,
        metavar="FILE",
        help="Path to a file holding the body text.",
    )
    p.add_argument(
        "--sent-log",
        type=Path,
        default=Path("sent.log"),
        metavar="FILE",
        help="Record of addresses already sent; these are skipped "
        "on re-run (default: %(default)s). Use a separate log "
        "per campaign.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the roster, placeholders and attachments, "
        "then report what would be sent. Sends nothing.",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Pause between messages (default: %(default)s). "
        "Raise this if the provider rate-limits you.",
    )
    p.add_argument(
        "--host",
        default="smtp.gmail.com",
        metavar="HOSTNAME",
        help="SMTP server (default: %(default)s).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=465,
        metavar="PORT",
        help="SMTP port (default: %(default)s).",
    )
    p.add_argument(
        "--no-ssl",
        action="store_true",
        help="Use plain SMTP instead of SMTP_SSL. Testing only.",
    )
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt, for scripted use.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.body_file:
        if not args.body_file.is_file():
            sys.exit(f"Error: body file not found: {args.body_file}")
        template = args.body_file.read_text(encoding="utf-8")
    else:
        template = args.message

    try:
        participants, headers = load_roster(args.roster, args.email_col)
    except (OSError, ValueError) as e:
        sys.exit(f"Error: {e}")

    if not participants:
        sys.exit("Error: roster contains no participants.")

    # Validate every {placeholder} in the template against real columns
    # BEFORE resolving a single attachment or sending a single email.
    needed = referenced_placeholders(template)
    unknown = needed - set(headers)
    if unknown:
        sys.exit(
            f"Error: template references unknown placeholder(s) "
            f"{sorted(unknown)}.\n"
            f"Available columns: {headers}\n"
            "If you meant a literal brace in the body (for example R code "
            "such as function(x) { x + 1 }), double it: {{ and }}."
        )

    has_attachment_col = args.attachment_col in headers

    # Pre-flight: resolve and check every attachment file before anything sends.
    missing = []
    for shared in args.attach:
        if not shared.is_file():
            missing.append(f"  (--attach, all recipients) -> {shared}")
    if args.attachment_name_col and args.attachment_name_col not in headers:
        sys.exit(
            f"Error: --attachment-name-col {args.attachment_name_col!r} not "
            f"found. Available columns: {headers}"
        )

    resolved: list[list[Path]] = []
    shown: list[list[str]] = []
    name_errors: list[str] = []
    for row in participants:
        raw = row.get(args.attachment_col, "") if has_attachment_col else ""
        filenames = parse_attachment_list(raw, args.attachment_sep)
        paths = [args.attachment_dir / name for name in filenames]
        own_count = len(paths)
        paths.extend(args.attach)
        resolved.append(paths)

        if args.attachment_name_col:
            labels = parse_attachment_list(
                row.get(args.attachment_name_col, ""), args.attachment_sep
            )
            if len(labels) != own_count:
                name_errors.append(
                    f"  {row[args.email_col]}: {own_count} attachment(s) but "
                    f"{len(labels)} display name(s)"
                )
                labels = [p.name for p in paths[:own_count]]
            shown.append(labels + [p.name for p in args.attach])
        else:
            shown.append([p.name for p in paths])

        for path in paths:
            if not path.is_file() and path not in args.attach:
                missing.append(f"  {row[args.email_col]} -> {path}")

    if name_errors:
        sys.exit(
            "Error: display-name count does not match attachment count:\n"
            + "\n".join(name_errors)
        )
    if missing:
        sys.exit(
            "Error: missing attachment file(s); nothing sent:\n" + "\n".join(missing)
        )

    seen = set()
    duplicates = []
    for row in participants:
        addr = row[args.email_col].lower()
        if addr in seen:
            duplicates.append(addr)
        seen.add(addr)
    if duplicates:
        sys.exit(f"Error: duplicate addresses in roster: {sorted(set(duplicates))}")

    already_sent: set[str] = set()
    if args.sent_log.is_file():
        already_sent = {
            line.strip().lower()
            for line in args.sent_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    pending_idx = [
        i
        for i, r in enumerate(participants)
        if r[args.email_col].lower() not in already_sent
    ]
    print(
        f"Roster: {len(participants)} | already sent: {len(already_sent)} "
        f"| to send: {len(pending_idx)}"
    )

    if args.dry_run:
        for i in pending_idx:
            row = participants[i]
            names = ", ".join(shown[i]) or "(no attachments)"
            print(f"  [DRY] {row[args.email_col]:<28} {names}")
        if args.cc:
            print(
                f"  [DRY] Cc on every message: {', '.join(args.cc)} "
                f"-> {len(pending_idx)} emails"
            )
        if args.bcc:
            print(
                f"  [DRY] Bcc on every message: {', '.join(args.bcc)} "
                f"-> {len(pending_idx)} emails"
            )
        if args.copy_to:
            print(f"  [DRY] One copy to: {args.copy_to} -> 1 email")
        print("\nDry run complete. Nothing was sent.")
        return

    if not pending_idx:
        print("Nothing to do.")
        return

    if args.cc or args.bcc:
        copied = ", ".join(args.cc + args.bcc)
        print(
            f"\nNOTE: {copied} will receive {len(pending_idx)} separate "
            f"emails, one per recipient.\n"
            f"      For a single copy of this campaign, use --copy-to instead."
        )

    if not args.yes:
        reply = input(
            f"\nReady to send {len(pending_idx)} email(s). Type YES to continue: "
        )
        if reply.strip() != "YES":
            sys.exit("Aborted: confirmation not received. Nothing was sent.")

    sender = os.environ.get("WORKSHOP_EMAIL")
    password = os.environ.get("WORKSHOP_PASSWORD")

    if not sender:
        sys.exit(textwrap.dedent("""\
            Error: WORKSHOP_EMAIL is not set.

            Linux / WSL2 (bash, zsh):

                export WORKSHOP_EMAIL="your_email@example.com"

            Windows PowerShell:

                $env:WORKSHOP_EMAIL="your_email@example.com"
            """))

    if not password and not args.no_ssl:
        sys.exit(textwrap.dedent("""\
            Error: WORKSHOP_PASSWORD is not set.

            Linux / WSL2 (bash, zsh):

                export WORKSHOP_PASSWORD="your_gmail_app_password"

            Windows PowerShell:

                $env:WORKSHOP_PASSWORD="your_gmail_app_password"

            For Gmail, use an App Password rather than your account password.
            """))

    failures = 0
    sent_this_run = 0
    started = time.perf_counter()
    try:
        if args.no_ssl:
            smtp = smtplib.SMTP(args.host, args.port, timeout=30)
        else:
            smtp = smtplib.SMTP_SSL(
                args.host, args.port, timeout=30, context=ssl.create_default_context()
            )
        with smtp:
            if password:
                smtp.login(sender, password)
            with args.sent_log.open("a", encoding="utf-8") as log:
                for progress, i in enumerate(pending_idx, start=1):
                    row = participants[i]
                    to = row[args.email_col]
                    body = template.format_map(row)

                    msg = build_message(
                        sender,
                        to,
                        args.subject,
                        body,
                        resolved[i],
                        shown[i],
                        cc=args.cc,
                        bcc=args.bcc,
                    )

                    try:
                        smtp.send_message(msg)
                    except smtplib.SMTPRecipientsRefused as e:
                        print(
                            f"  [{progress}/{len(pending_idx)}] REFUSED {to}: {e}",
                            file=sys.stderr,
                        )
                        failures += 1
                        continue
                    log.write(f"{to.lower()}\n")
                    log.flush()
                    sent_this_run += 1
                    names = ", ".join(shown[i]) or "(no attachments)"
                    print(f"  [{progress}/{len(pending_idx)}] sent {to} ({names})")
                    if args.delay and progress < len(pending_idx):
                        time.sleep(args.delay)

            if args.copy_to and sent_this_run:
                try:
                    smtp.send_message(
                        build_copy_message(
                            sender,
                            args.copy_to,
                            args.subject,
                            template,
                            args.attach,
                            sent_this_run,
                        )
                    )
                    print(f"  copy sent to {args.copy_to}")
                except smtplib.SMTPException as exc:
                    print(
                        f"  WARNING: copy to {args.copy_to} failed: {exc}",
                        file=sys.stderr,
                    )
    except smtplib.SMTPAuthenticationError:
        sys.exit("Authentication failed. Check WORKSHOP_PASSWORD (Gmail app password).")
    except (OSError, smtplib.SMTPException) as e:
        sys.exit(
            f"Connection/transport failure after {sent_this_run} sent this "
            f"run ({len(pending_idx) - sent_this_run} not attempted). "
            f"Re-run to resume. Error: {e}"
        )

    elapsed = time.perf_counter() - started
    print("\n" + "-" * 40)
    print(f"Sent successfully : {sent_this_run}")
    print(f"Failed            : {failures}")
    print(f"Skipped (prior)   : {len(already_sent)}")
    print(f"Duration          : {elapsed:.1f} seconds")
    print("-" * 40)
    if failures:
        sys.exit(f"Completed with {failures} failure(s).")


if __name__ == "__main__":
    main()
