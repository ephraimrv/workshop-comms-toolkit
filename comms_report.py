r"""Generate a participant communications log from ``campaigns.jsonl``.

This module reads a JSONL manifest of email campaigns, groups runs belonging
to the same campaign, verifies each record against the files it references,
and renders a single printable HTML document suitable for submission as
programme documentation.

Recipient addresses are never read into the report. Sent logs are opened only
to count lines, so the resulting document contains counts alone.

Schema
------
One JSON object per line. Both the hand-written and the tool-generated field
names are accepted::

    hand-written        tool-generated
    ------------        --------------
    sent_at             run_at
    recipient_count     sent_this_run
    session             meta.session

Examples
--------
Render every campaign to a dated report::

    python comms_report.py -c campaigns.jsonl -o Communications_Log.html

Check the manifest without writing anything::

    python comms_report.py -c campaigns.jsonl --check

Render without the full message bodies, for a summary-only version::

    python comms_report.py -c campaigns.jsonl -o Summary.html --no-bodies

Render only the communications belonging to one session, leaving the default
(no ``--session``) to produce the complete, cumulative record::

    python comms_report.py -c campaigns.jsonl -o Session1_Log.html --session 1
"""

__author__ = "Jan Ephraim R. Vallente"
__version__ = "1.1.0"

import argparse
import html
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Fields accepted under either name, mapped to the canonical name used here.
ALIASES = {
    "sent_at": "run_at",
    "recipient_count": "sent_this_run",
}

REQUIRED = ("campaign_id", "run_at", "subject")


def normalise(record: dict, lineno: int) -> dict:
    """Return the record with legacy field names mapped to canonical ones.

    Hand-written manifests predate the run-oriented schema and use
    ``sent_at``/``recipient_count``. Rather than force a rewrite of existing
    records, both spellings are accepted and reconciled here, at the single
    point where records enter the program.
    """
    out = dict(record)
    for legacy, canonical in ALIASES.items():
        if legacy in out and canonical not in out:
            out[canonical] = out.pop(legacy)
        out.pop(legacy, None)

    # A bare `session` key predates the generic meta object.
    meta = dict(out.get("meta") or {})
    if "session" in out:
        meta.setdefault("session", out.pop("session"))
    out["meta"] = meta

    out.setdefault("status", "complete")
    out.setdefault("failures", 0)
    out.setdefault("skipped_prior", 0)
    out.setdefault("sent_this_run", 0)
    out.setdefault("attachments", [])
    out.setdefault("shared_attachments", [])
    out.setdefault("notes", "")

    missing = [f for f in REQUIRED if not out.get(f)]
    if missing:
        raise ValueError(f"line {lineno}: missing required field(s) {missing}")

    try:
        datetime.fromisoformat(out["run_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"line {lineno}: run_at {out['run_at']!r} is not ISO 8601 "
            f"(expected e.g. 2026-07-22T20:15:00+08:00)"
        ) from exc

    return out


def load_campaigns(path: Path) -> list[dict]:
    """Read the JSONL manifest, reporting every malformed line at once."""
    problems: list[str] = []
    records: list[dict] = []

    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(
                    f"  line {lineno}: not valid JSON ({exc.msg}). "
                    f"Each line must hold one complete object on one physical "
                    f"line; pretty-printed objects will not parse."
                )
                continue
            try:
                records.append(normalise(raw, lineno))
            except ValueError as exc:
                problems.append(f"  {exc}")

    if problems:
        raise ValueError(
            f"{path} has {len(problems)} malformed line(s):\n" + "\n".join(problems)
        )
    if not records:
        raise ValueError(f"{path} contains no campaign records.")
    return records


def count_log_lines(path: Path) -> int | None:
    """Return the number of addresses in a sent log, or None if unreadable.

    The file is opened only to count non-blank lines. Addresses are never
    retained, so they cannot reach the rendered document.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return None


def attachments_of(record: dict) -> list[str]:
    """Return every attachment name referenced by a record, in order."""
    names = list(record.get("attachments") or [])
    names += list(record.get("shared_attachments") or [])
    per = record.get("per_recipient_attachments")
    if isinstance(per, dict) and per.get("dir"):
        count = per.get("count")
        suffix = f" ({count} files)" if count else ""
        names.append(f"[per recipient: {per['dir']}/]{suffix}")
    return names


def group_runs(records: list[dict]) -> list[dict]:
    """Collapse runs into campaigns, preserving chronological order.

    A single campaign may span several runs when a send is interrupted and
    resumed. The campaign's date is that of its first attempt; its recipient
    total is the sum across runs.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        buckets[rec["campaign_id"]].append(rec)

    campaigns = []
    for campaign_id, runs in buckets.items():
        runs.sort(key=lambda r: r["run_at"])
        first, last = runs[0], runs[-1]
        campaigns.append(
            {
                "campaign_id": campaign_id,
                "run_at": first["run_at"],
                "completed_at": last["run_at"],
                "runs": runs,
                "subject": last["subject"],
                "body_file": last.get("body_file"),
                "body_text": last.get("body_text"),
                "sent_log": last.get("sent_log"),
                "notes": last.get("notes", ""),
                "meta": last.get("meta", {}),
                "attachments": attachments_of(last),
                "total_sent": sum(r["sent_this_run"] for r in runs),
                "total_failures": sum(r["failures"] for r in runs),
            }
        )
    campaigns.sort(key=lambda c: c["run_at"])
    return campaigns


def verify(campaign: dict, base: Path) -> list[str]:
    """Return a list of human-readable discrepancies for one campaign."""
    warnings: list[str] = []

    body_file = campaign.get("body_file")
    if body_file:
        if not (base / body_file).is_file():
            warnings.append(f"body file not found: {body_file}")
    elif not campaign.get("body_text"):
        warnings.append("no body_file and no body_text; message text unrecorded")

    sent_log = campaign.get("sent_log")
    if sent_log:
        counted = count_log_lines(base / sent_log)
        if counted is None:
            warnings.append(f"sent log not found: {sent_log}")
        elif counted != campaign["total_sent"]:
            warnings.append(
                f"count mismatch: manifest says {campaign['total_sent']}, "
                f"sent log holds {counted}"
            )
    else:
        warnings.append("no sent_log recorded; recipient count unverifiable")

    for name in campaign["attachments"]:
        if name.startswith("[per recipient:"):
            continue
        if not (base / name).is_file():
            warnings.append(f"attachment not found: {name}")

    return warnings


def read_body(campaign: dict, base: Path) -> str:
    """Return the archived message text, or a placeholder if unavailable."""
    if campaign.get("body_text"):
        return campaign["body_text"]
    body_file = campaign.get("body_file")
    if not body_file:
        return "[Message text was not archived.]"
    try:
        return (base / body_file).read_text(encoding="utf-8")
    except OSError:
        return f"[Message text unavailable: {body_file} could not be read.]"


def fmt_datetime(iso: str) -> str:
    """Render an ISO 8601 timestamp as e.g. '22 July 2026, 8:15 PM'."""
    dt = datetime.fromisoformat(iso)
    hour = dt.hour % 12 or 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    return f"{dt.day} {dt:%B} {dt.year}, {hour}:{dt:%M} {meridiem}"


CSS = """
@page { size: A4; margin: 18mm; }
body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.5; color: #1a1a1a; max-width: 760px; margin: 32px auto;
       padding: 0 20px; }
h1 { font-size: 17pt; margin: 0 0 4px 0; }
.sub { color: #666; font-size: 9pt; }
.byline { color: #666; font-size: 9pt; border-bottom: 2px solid #333;
          padding-bottom: 12px; margin-bottom: 20px; }
h2 { font-size: 12pt; margin: 26px 0 8px 0; padding-bottom: 4px;
     border-bottom: 1.5px solid #333; }
h3 { font-size: 11pt; margin: 22px 0 4px 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9.5pt; }
th, td { border: 1px solid #ddd; padding: 5px 7px; text-align: left;
         vertical-align: top; }
th { background: #f4f4f4; font-size: 8.5pt; text-transform: uppercase;
     letter-spacing: 0.4px; }
pre { background: #f7f7f7; border: 1px solid #e0e0e0; border-left: 3px solid #999;
      border-radius: 4px; padding: 12px 15px; font-size: 9pt; line-height: 1.45;
      white-space: pre-wrap; word-wrap: break-word; font-family: inherit; }
.meta { font-size: 9pt; color: #555; margin: 4px 0 8px 0; }
.warn { background: #fdf3f2; border-left: 3px solid #c0392b; padding: 8px 13px;
        margin: 8px 0; font-size: 9pt; }
.ok { color: #2e8b57; font-size: 9pt; }
.foot { margin-top: 32px; padding-top: 12px; border-top: 1px solid #ccc;
        font-size: 8.5pt; color: #555; }
"""


def render(
    campaigns: list[dict],
    base: Path,
    title: str,
    owner: str,
    lead: str,
    programme: str,
    include_bodies: bool,
    session: str | None = None,
) -> str:
    """Render the full report as a standalone HTML document."""
    e = html.escape
    generated = datetime.now().astimezone()
    out: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        f"<title>{e(title)}</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        f"<h1>{e(title)}</h1>",
        (
            '<div class="sub">Record of all electronic communications issued to '
            "participants</div>"
        ),
        (
            f'<div class="byline">{e(programme)}<br>Programme Lead: {e(lead)}<br>'
            f"Document Owner: {e(owner)}<br>"
            f"Generated {generated:%d %B %Y}</div>"
        ),
    ]

    total_campaigns = len(campaigns)
    total_messages = sum(c["total_sent"] for c in campaigns)
    out.append("<h2>Summary</h2>")
    out.append(
        f"<p>This record covers <strong>{total_campaigns}</strong> campaign(s) "
        f"comprising <strong>{total_messages}</strong> individual message(s). "
        f"Recipient addresses are held separately and are deliberately excluded "
        f"from this document.</p>"
    )
    if session is not None:
        out.append(
            f"<p><strong>Scope:</strong> this report includes only communications "
            f"belonging to Session {e(session)}; it is not the complete, "
            f"cumulative record.</p>"
        )

    out.append("<table>")
    out.append(
        "<thead><tr><th>#</th><th>Date sent</th><th>Subject</th>"
        "<th>Recipients</th><th>Attachments</th></tr></thead><tbody>"
    )
    for n, c in enumerate(campaigns, start=1):
        att = "<br>".join(e(Path(a).name) for a in c["attachments"]) or "&mdash;"
        out.append(
            f"<tr><td>{n}</td><td>{e(fmt_datetime(c['run_at']))}</td>"
            f"<td>{e(c['subject'])}</td><td>{c['total_sent']}</td>"
            f"<td>{att}</td></tr>"
        )
    out.append("</tbody></table>")

    all_warnings = {c["campaign_id"]: verify(c, base) for c in campaigns}
    flagged = {k: v for k, v in all_warnings.items() if v}
    out.append("<h2>Verification</h2>")
    if flagged:
        out.append(
            f"<p>{len(flagged)} of {total_campaigns} record(s) could not be fully "
            f"verified against the files they reference:</p>"
        )
        for campaign_id, warns in flagged.items():
            items = "".join(f"<li>{e(w)}</li>" for w in warns)
            out.append(
                f'<div class="warn"><strong>{e(campaign_id)}</strong>'
                f"<ul>{items}</ul></div>"
            )
    else:
        out.append(
            '<p class="ok">Every record was verified against its archived message '
            "body and sent log. Recipient counts agree with the logs in all "
            "cases.</p>"
        )

    if include_bodies:
        out.append("<h2>Messages in full</h2>")
        for n, c in enumerate(campaigns, start=1):
            out.append(f"<h3>{n}. {e(c['subject'])}</h3>")
            bits = [
                f"Sent {e(fmt_datetime(c['run_at']))}",
                f"{c['total_sent']} recipient(s)",
            ]
            if len(c["runs"]) > 1:
                bits.append(
                    f"{len(c['runs'])} runs, completed "
                    f"{e(fmt_datetime(c['completed_at']))}"
                )
            if c["total_failures"]:
                bits.append(f"{c['total_failures']} failure(s)")
            for key, value in (c.get("meta") or {}).items():
                bits.append(f"{e(str(key))}: {e(str(value))}")
            out.append(f'<div class="meta">{" &middot; ".join(bits)}</div>')
            if c["attachments"]:
                names = ", ".join(e(Path(a).name) for a in c["attachments"])
                out.append(f'<div class="meta">Attachments: {names}</div>')
            if c["notes"]:
                out.append(f'<div class="meta">{e(c["notes"])}</div>')
            out.append(f"<pre>{e(read_body(c, base))}</pre>")

    out.append(
        f'<div class="foot">Generated by comms_report.py v{__version__} from '
        f"campaigns.jsonl. Recipient addresses are stored separately in per-campaign "
        f"sent logs and are not reproduced here.</div>"
    )
    out += ["</body>", "</html>"]
    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    """Build and parse the command-line interface."""
    p = argparse.ArgumentParser(
        prog="comms_report.py",
        description=(
            "Render a participant communications log from campaigns.jsonl, "
            "verifying each record against its archived body and sent log."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "-c",
        "--campaigns",
        type=Path,
        default=Path("campaigns.jsonl"),
        metavar="FILE",
        help="JSONL manifest (default: %(default)s).",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="Write the report here. Omit with --check.",
    )
    p.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        metavar="DIRECTORY",
        help="Root for resolving body, log and attachment paths "
        "(default: the manifest's own directory).",
    )
    p.add_argument(
        "--title",
        default="Participant Communications Log",
        metavar="TEXT",
        help="Document title (default: %(default)r).",
    )
    p.add_argument(
        "--owner",
        default="Jan Ephraim R. Vallente",
        metavar="NAME",
        help="Document owner (default: %(default)r).",
    )
    p.add_argument(
        "--lead",
        default="Dr. Imelda L. Forteza",
        metavar="NAME",
        help="Programme lead (default: %(default)r).",
    )
    p.add_argument(
        "--programme",
        default="BSP–MMSU Workshop Series · Balik Scientist Program · "
        "Mariano Marcos State University",
        metavar="TEXT",
        help="Programme line for the header.",
    )
    p.add_argument(
        "--session",
        metavar="ID",
        help="Include only campaigns tagged with this session id (compared "
        "against meta.session). Omit to render the complete, cumulative "
        "record.",
    )
    p.add_argument(
        "--no-bodies",
        action="store_true",
        help="Omit full message texts; render the summary only.",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Validate the manifest and report discrepancies without "
        "writing any file.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        records = load_campaigns(args.campaigns)
    except (OSError, ValueError) as exc:
        sys.exit(f"Error: {exc}")

    if args.session is not None:
        present = sorted(
            {
                str(r["meta"]["session"])
                for r in records
                if r["meta"].get("session") is not None
            }
        )
        records = [
            r for r in records if str(r["meta"].get("session")) == args.session
        ]
        if not records:
            sys.exit(
                f"Error: no campaigns match --session {args.session} "
                f"(sessions present: {', '.join(present) or 'none'})."
            )

    base = args.base_dir or args.campaigns.resolve().parent
    campaigns = group_runs(records)

    print(f"Manifest : {args.campaigns}")
    if args.session is not None:
        print(f"Filter   : session == {args.session}")
    print(f"Runs     : {len(records)}  ->  campaigns: {len(campaigns)}")
    print(f"Messages : {sum(c['total_sent'] for c in campaigns)}")

    problems = 0
    for c in campaigns:
        warns = verify(c, base)
        if warns:
            problems += 1
            print(f"\n  {c['campaign_id']}")
            for w in warns:
                print(f"    - {w}")
    if not problems:
        print("All records verified against their bodies and sent logs.")

    if args.check:
        print("\nCheck complete. Nothing was written.")
        sys.exit(1 if problems else 0)

    if not args.output:
        sys.exit("Error: --output is required unless --check is given.")

    document = render(
        campaigns,
        base,
        args.title,
        args.owner,
        args.lead,
        args.programme,
        include_bodies=not args.no_bodies,
        session=args.session,
    )
    try:
        args.output.write_text(document, encoding="utf-8")
    except OSError as exc:
        sys.exit(f"Error: could not write {args.output}: {exc}")

    print(f"\nWrote {args.output} ({len(document):,} bytes)")
    if problems:
        print(
            f"Note: {problems} record(s) carry verification warnings, which "
            f"appear in the document."
        )


if __name__ == "__main__":
    main()