# Workshop Comms Toolkit

Two command-line tools for running participant communications on a training
programme: one that sends personalised bulk email with per-recipient
attachments, and one that turns a record of those sends into submittable
programme documentation.

Written in Python 3.12 with the standard library only. No dependencies.

---

## Why this exists

These were built for the BSP–MMSU Workshop Series — a three-session R training
programme for biologists at Mariano Marcos State University, run under the
Philippine Department of Science and Technology's Balik Scientist Program.

The practical problem: a roster of several dozen registrants, several rounds of
pre-session instructions, and a funding body that requires a documented record
of every communication sent. Attendance varies from session to session —
registrants drop off, others join as walk-ins — so the eventual audience is not
a fixed number known in advance. Doing the communications by hand is slow, and
doing it by hand *twice* — once to send, once to write it up — is slower still.

So the sending and the record-keeping were made the same operation.

---

## The tools

### `mail_merge.py`

Sends one personalised email per row of a CSV or TSV roster.

- `{Column}` placeholders drawn from any roster column
- Per-recipient attachments, shared attachments, or both
- Attachment display names independent of the filenames on disk, so files can
  be stored under safe ASCII serials while recipients see readable names
- Every attachment verified to exist *before* the first message is sent
- Resumable: addresses already recorded in the sent log are skipped
- Optionally appends a one-line JSON record of each run to the campaign
  manifest (`--manifest`), so the send and its documentation are one step
- `--dry-run` validates the roster, placeholders and attachments without
  sending
- Interactive confirmation before any real send

```bash
# always first
python mail_merge.py -R roster.csv --email-col Username -b body.txt --dry-run

# a real send that also records itself in the manifest
python mail_merge.py -R roster.csv --email-col Username \
    -b body.txt -s "Session 2 materials" \
    --sent-log logs/session2.log \
    --manifest campaigns.jsonl \
    --campaign-id session2-materials-2026-07-30 --session 2 \
    --copy-to lead@example.edu
```

### `comms_report.py`

Reads the campaign manifest and renders a single printable HTML document: a
summary table of every campaign, the full text of each message, and a
verification section reconciling the manifest against the files it references.

```bash
python comms_report.py -c campaigns.jsonl --check          # validate only
python comms_report.py -c campaigns.jsonl -o Report.html   # render everything
python comms_report.py -c campaigns.jsonl -o S1.html --session 1   # one session
```

`--check` exits non-zero when any record fails verification, so it can gate a
build step. Verification reconciles each recipient count against its sent log,
confirms archived bodies and attachments exist, and warns when the date in a
`campaign_id` disagrees with the date it was sent. Passing `--session N`
restricts the report to one session (see [Manifest schema](#manifest-schema));
omitting it renders the complete, cumulative record.

---

## Manifest schema

`campaigns.jsonl` holds one JSON object per line. Each line records a single
*run*, not a campaign (see [A manifest line describes a *run*, not a
*campaign*](#a-manifest-line-describes-a-run-not-a-campaign) below for why).
`comms_report.py` reconciles the fields below, and `mail_merge.py --manifest`
emits them automatically.

This section is the single authoritative definition of these fields. The tool
docstrings and any notes point here rather than restate them.

| Field | Meaning |
|---|---|
| `campaign_id` | Stable identifier, reused verbatim across resumed runs so they group into one campaign. Convention: `<slug>-YYYY-MM-DD`, where the date is the **send date**. `comms_report.py --check` warns when that date disagrees with `run_at`. |
| `run_at` | ISO-8601 timestamp of the run. Legacy records may spell this `sent_at`. |
| `sent_this_run` | Addresses this run sent; summed across runs for a campaign's total, and reconciled against the sent log. Legacy: `recipient_count`. |
| `meta.session` | The workshop session the campaign concerns — defined below. Legacy records may carry a top-level `session`. |
| `subject` | Subject line, as sent. |
| `body_file` / `body_text` | Archived message text, by path or inline. |
| `sent_log` | Path to the run's sent log; its non-blank line count must equal the campaign's summed `sent_this_run`. Empty or absent for a message sent by hand — the report then marks the count unverifiable rather than wrong. |
| `attachments` / `shared_attachments` / `per_recipient_attachments` | Files sent to a single record, to everyone, or one per recipient. |
| `failures` / `skipped_prior` / `status` | Run outcome: sends refused, addresses already sent in an earlier run, and whether the run completed or was interrupted. |
| `notes` | Free-text record of anything notable about the run — including whether it was sent outside the tool. |

### `session` — the one definition

`session` identifies the workshop session a communication belongs to. In the
ordinary case that is simply the session it is *about*, not the day it was sent:
Session 1's installation reminders, its certificate announcement and its
evaluation form are all `session: 1`, whichever day each goes out. The Session 1
evaluation form, sent on 25 July for a workshop held on 23 July, is `session: 1`,
because verifying the attendance sheet and preparing the form cannot happen on
the day itself.

A session's communications are treated as closed once its evaluation form has
been sent; a message sent after that point belongs to the *next* session, even
when it revisits earlier material. So the catch-up sent on 26 July to
registrants who had missed the Session 1 setup emails is `session: 2` — Session
1's cycle had already closed.

`session` MUST NOT be read as the date sent, the sending batch or run, or a
chronological index of campaigns.

Canonical type is an integer (`1`, `2`, `3`); a quoted string (`"1"`) is
accepted for backward compatibility but should not be written by hand. Filter a
report to one session with `comms_report.py --session 1`.

---

## Design notes

The decisions worth explaining, and why they went the way they did.

### Recipient addresses never reach the report

Sent logs are opened only to count non-blank lines. The addresses are never
bound to a variable that reaches the renderer, so they cannot appear in the
output document by accident. Verified by regex-scanning generated reports for
address patterns.

This matters because the report is submitted to a funding body. A recipient
list belongs in the operational record, not in a document that gets circulated.
The logs themselves are gitignored and never leave the machine.

### The sent log is written *after* the send, not before

```python
try:
    smtp.send_message(msg)
except smtplib.SMTPRecipientsRefused:
    failures += 1
    continue          # nothing is recorded
log.write(f"{to.lower()}\n")
log.flush()
```

The log's only job is idempotency, so its invariant is *an address appears here
if and only if a message reached the server*. Recording before the attempt
would silently skip a recipient whose send failed. Flushing per line means an
interrupted run resumes correctly rather than re-sending to everyone.

### `campaigns.jsonl`, not `campaigns.json`

One JSON object per line, append-only. A JSON array would require reading and
rewriting the whole file to add one record, and a crash mid-write leaves the
closing bracket unwritten — which makes the *entire* file unparseable. With
line-delimited JSON a crash costs at most the record being written; every line
above it stays independently valid.

### A manifest line describes a *run*, not a *campaign*

Because sends are resumable, one campaign can span several runs. If each line
were a campaign, an interrupted send of 61 that resumed after 40 would be
reported as two campaigns of 40 and 21.

Lines are therefore events, and `comms_report.py` groups them by
`campaign_id` at read time — earliest run for the date, sum of runs for the
total. Aggregation is the report's job; the log stores what happened.

### `--copy-to` is not `--cc`

`--cc` and `--bcc` add headers to *every* message, so a copied address receives
one email per recipient. That is correct for an archive mailbox and wrong for a
human being.

`--copy-to` sends exactly one message after the run, carrying the *unrendered*
template — because no single recipient's version represents the campaign — plus
the recipient count and any shared attachments. Both flags exist because both
needs are real; the help text and a pre-send warning make the difference hard
to get wrong.

### Two tools rather than one

`mail_merge.py` sends. `comms_report.py` documents. Merging them would have
meant a mail tool that also knows about report formatting, and the reporting
would have been unusable for campaigns sent by other means. The manifest file
is the seam between them.

### Backward-compatible manifest schema

Early records were hand-written with `sent_at` and `recipient_count` before the
run-oriented schema settled. Rather than force a rewrite of existing records,
`normalise()` maps legacy field names to canonical ones at the single point
where records enter the program. Old and new lines coexist in the same file, and
`mail_merge.py --manifest` writes the canonical spelling
(`run_at`, `sent_this_run`, `meta.session`) so the legacy form is only ever read,
never freshly written. The field list itself lives in
[Manifest schema](#manifest-schema), not here.

### Everything fails before anything sends

Roster parsing reports *all* malformed rows at once rather than one per re-run.
Placeholders are validated against real column headers. Every attachment path
is resolved and checked. Duplicate addresses are rejected. Only then does the
tool ask for confirmation.

The alternative — discovering a missing certificate at recipient 43 — leaves a
campaign half-sent and a person to apologise to.

---

## Testing

Both tools were exercised against a local SMTP server during development:

```bash
pip install aiosmtpd
python -m aiosmtpd -n -l localhost:1025

python mail_merge.py -R roster.csv --email-col Username -b body.txt \
    --no-ssl --host localhost --port 1025 --delay 0 \
    --sent-log /tmp/test.log -y
```

`comms_report.py` was checked against malformed manifests — pretty-printed
JSON, missing required fields, non-ISO timestamps, empty and absent files —
and against a manifest whose recipient count deliberately disagreed with its
sent log.

The `--manifest` emitter was exercised end to end against the same local
server: a send appends one run record, and re-running the same `campaign_id`
after adding a recipient produces a second run that `comms_report.py` groups
into one campaign and reconciles against the sent log.

There is no automated test suite yet. See Limitations.

---

## Repository layout

```
├── mail_merge.py        # sending
├── comms_report.py      # reporting
├── campaigns.jsonl      # campaign manifest, one JSON object per line
├── bodies/              # archived message templates
├── attachments/         # documents distributed to participants
└── logs/                # sent logs — gitignored, never published
```

`logs/` is excluded from version control. It contains participant email
addresses and is retained only on the operator's machine.

---

## Limitations

Stated plainly, because they are the next things to fix.

- **No automated tests.** `main()` creates its SMTP connection inline, so there
  is no seam to inject a fake transport. Testing currently requires a live
  local server. Extracting the send loop into a function taking an
  already-connected SMTP object is the obvious next refactor.
- **Communications sent outside the tool still need a manual line.**
  `mail_merge.py --manifest` records everything sent through the tool
  automatically. A message sent by hand — an individual email to a colleague,
  say — must still have its manifest line written by hand, and is recorded with
  an empty `sent_log`, which the report marks as unverifiable rather than
  wrong.
- **Plain-text bodies only.** No HTML multipart alternative.
- **Gmail-oriented defaults.** Host and port are configurable, but the
  credential guidance assumes an app password.

---

## Requirements

Python 3.12 or later. Standard library only.
`aiosmtpd` is needed for local testing, not for use.

Credentials are read from the environment, never from a file:

```bash
export WORKSHOP_EMAIL="you@example.com"
export WORKSHOP_PASSWORD="your_app_password"
```

---

## Licence

MIT. See [LICENSE](LICENSE).

Written by Jan Ephraim R. Vallente.
