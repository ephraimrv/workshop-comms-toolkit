# BSP–MMSU Workshop Operations Toolkit

A set of command-line tools for running a multi-session training programme end to end: validating a messy attendance export, deciding who earned which certificate, generating the certificate PDFs, sending them (and every other participant communication) as personalised bulk email, and turning the record of those sends into submittable programme documentation.

Written in Python 3.12 with the standard library plus `pypdf` and `reportlab` for the certificate stage. Built to run a real workshop, not to demonstrate a framework.

------

## Why this exists

These tools were built for the BSP–MMSU Workshop Series — a three-session R training programme for biologists at Mariano Marcos State University, run under the Philippine Department of Science and Technology's Balik Scientist Program.

The author served as research assistant for the series: handling the backend for the programme lead, troubleshooting installations during sessions, and compiling the participant-facing guides distributed alongside the workshop (several of which live in `attachments/`). The Python tools documented here are what made that workload tractable.

The practical problem had two halves that turned out to share a spine.

**Communications.** A roster of several dozen registrants, several rounds of pre-session instructions, and a funding body that requires a documented record of every message sent. Attendance varies from session to session — registrants drop off, others join late — so the eventual audience is not a fixed number known in advance. Doing this by hand is slow; doing it by hand *twice*, once to send and once to write it up, is slower still. So the sending and the record-keeping were made the same operation.

**Certificates.** Attendance is captured by an accumulating Google Form with no session column. Who attended which session — and therefore who earned a *Participation* certificate versus an *Attendance* one — has to be derived, not read off. Then a name has to be stamped onto the correct template, verbatim, for every person, and mailed to the right address. Done by hand across three sessions and dozens of people, this is both slow and error-prone in exactly the way that produces a wrong name on someone's certificate.

Both halves meet at a single CSV roster. That seam is what lets each tool do one job and hand off cleanly to the next.

------

## The pipeline

```
                      Google Forms export (accumulating, no session column)
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │  rollup_attendance.py  │  derive session + tier
                            └───────────────────────┘  per distinct person
                                        │
                                        ▼
                                 cert_roster.csv
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │   generate_cert.py     │  stamp PDFs, enrich roster
                            └───────────────────────┘
                                        │
                          certs/*.pdf  +  roster_out.csv
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │     mail_merge.py      │  send, log, record run
                            └───────────────────────┘
                                        │
                                 campaigns.jsonl
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │    comms_report.py     │  render submittable log
                            └───────────────────────┘

              roster_checks.py  ──  shared name/email validation,
                                    imported by rollup_attendance.py
                                    and generate_cert.py
```

`mail_merge.py` and `comms_report.py` also stand alone: every non-certificate communication in the series (setup reminders, house rules, troubleshooting guides, evaluation links) went out through the same two tools and is recorded in the same manifest.

------

## The tools

### `roster_checks.py`

Shared validation helpers imported by the tools that read rosters, so the same rules apply everywhere rather than each tool keeping its own copy that could drift.

- `clean_name` — strip surrounding whitespace and normalise to Unicode NFC, so a decomposed "n + combining tilde" renders as one glyph. Case is never touched.
- `structurally_valid_email` — cheap structural check: exactly one `@`, no whitespace, not `@`-terminated. Deliverability is out of scope.
- `likely_domain_typo` — flags a domain one edit away from a known-good one (`gmail.con` → `gmail.com`, `gmial.com` → `gmail.com`) using Damerau–Levenshtein distance, which counts an adjacent transposition as a single edit. Returns the probable intended domain for a human to confirm; never auto-corrects an address.

### `rollup_attendance.py`

Collapses the accumulating export into one row per person, with a derived tier, ready for `generate_cert.py`.

Session membership is derived from each row's submission timestamp against configurable date windows, because the real export has no session field. Tier is derived by counting *distinct* sessions per email using a set, so submitting twice inside one session's window does not inflate the count. The name kept for each person is the one from their most recent submission, on the assumption a later entry is more likely a correction.

It flags rather than silently resolves: missing or malformed emails, domain typos, unparseable timestamps, timestamps outside every window, and one name string appearing under two different addresses. Anything ambiguous surfaces for a human; nothing is quietly dropped.

```bash
python rollup_attendance.py eval.csv \
    --name-col "Full name" \
    --email-col "Email address" \
    --timestamp-col Timestamp \
    --session-window 1 2026-07-23 2026-07-29 \
    --session-window 2 2026-07-30 2026-08-05 \
    --session-window 3 2026-08-06 2026-08-31 \
    --sessions-for-participation 3 \
    --out cert_roster.csv
```

### `generate_cert.py`

Reads the rolled-up roster, stamps each name onto the matching template, and writes one certificate PDF per person plus an enriched roster ready for `mail_merge.py`.

Names are printed verbatim — the registration form asked how each person wants their name to appear, so case and spelling are never altered. The name is fitted to a safe width in closed form (text width is linear in point size, so the fit size is computed, not searched). Serials follow `<prefix>-<T>-<NNN>`, where `T` is `A` or `P` and the number is a single global sequence assigned after sorting the roster by email — a stable key that a later spelling fix cannot reassign to a different person. Tier is an input column, never decided here: this file's one job is stamping and naming, so it stays identical across workshops while the flags carry everything workshop-specific.

Output is `<out-dir>/<SERIAL>.pdf` plus `<out-dir>/roster_out.csv`, which adds two columns `mail_merge.py` reads directly: `attachments` (the ASCII-safe filename on disk) and `attachment_display` (the readable name the recipient sees).

```bash
python generate_cert.py cert_roster.csv \
    --serial-prefix BSP-2026-W1 \
    --template-attendance templates/ATTENDANCE.pdf \
    --template-participation templates/PARTICIPATION.pdf \
    --font fonts/Montserrat-Regular.ttf \
    --out-dir certs
```

> The font must be a **static** `Montserrat-Regular.ttf` (usWeightClass 400, no `fvar` table). The variable-font build some sources serve defaults to a Thin weight, and a metrics-only check will not catch it — only a visual check of the rendered PDF will. The university certificate templates are not included in this repository.

### `mail_merge.py`

Sends one personalised email per row of a CSV or TSV roster.

- `{Column}` placeholders drawn from any roster column
- Per-recipient attachments (`--attachment-col`), shared attachments (`--attach`), or both
- Attachment display names independent of the filenames on disk (`--attachment-name-col`), so files are stored under ASCII serials while recipients see readable names
- Every attachment verified to exist *before* the first message is sent
- Resumable: addresses already in the sent log are skipped
- `--manifest` appends a one-line JSON record of each run to the campaign manifest, making the send and its documentation one step
- `--copy-to` sends a single archival copy of the campaign after the run, distinct from `--cc`/`--bcc` which copy an address on *every* message
- `--dry-run` validates roster, placeholders, and attachments without sending
- Interactive confirmation before any real send

```bash
# always first
python mail_merge.py -R roster.csv --email-col email -b body.txt --dry-run

# mail the certificates: filename on disk vs. name shown in the email
python mail_merge.py -R certs/roster_out.csv \
    --email-col email \
    --attachment-col attachments \
    --attachment-name-col attachment_display \
    --attachment-dir certs \
    -b body.txt -s "Your BSP Workshop Certificate" \
    --sent-log logs/certs.log \
    --manifest campaigns.jsonl \
    --campaign-id certificates-2026-08-10 --session 3
```

### `comms_report.py`

Reads the campaign manifest and renders a single printable HTML document: a summary table of every campaign, the full text of each message, and a verification section reconciling the manifest against the files it references.

```bash
python comms_report.py -c campaigns.jsonl --check          # validate only
python comms_report.py -c campaigns.jsonl -o Report.html   # render everything
python comms_report.py -c campaigns.jsonl -o S1.html --session 1
```

`--check` exits non-zero when any record fails verification, so it can gate a build step. Verification reconciles each recipient count against its sent log, confirms archived bodies and attachments exist, and warns when the date in a `campaign_id` disagrees with the date it was sent.

> The rendered reports are operational records, not repository artefacts. Like `logs/` and `bodies/`, they stay on the operator's machine and are excluded from version control — they contain message bodies and internal correspondence that have no place in a public repo.

------

## Manifest schema

`campaigns.jsonl` holds one JSON object per line. Each line records a single *run*, not a campaign. `comms_report.py` reconciles the fields below, and `mail_merge.py --manifest` emits them automatically.

This section is the single authoritative definition of these fields.

| Field                                                        | Meaning                                                      |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| `campaign_id`                                                | Stable identifier, reused verbatim across resumed runs so they group into one campaign. Convention: `<slug>-YYYY-MM-DD`, where the date is the **send date**. `comms_report.py --check` warns when that date disagrees with `run_at`. |
| `run_at`                                                     | ISO-8601 timestamp of the run. Legacy records may spell this `sent_at`. |
| `sent_this_run`                                              | Addresses this run sent; summed across runs for a campaign's total, and reconciled against the sent log. Legacy: `recipient_count`. |
| `meta.session`                                               | The workshop session the campaign concerns — defined below. Legacy records may carry a top-level `session`. |
| `subject`                                                    | Subject line, as sent.                                       |
| `body_file` / `body_text`                                    | Archived message text, by path or inline.                    |
| `sent_log`                                                   | Path to the run's sent log; its non-blank line count must equal the campaign's summed `sent_this_run`. Empty or absent for a message sent by hand — the report marks the count unverifiable rather than wrong. |
| `attachments` / `shared_attachments` / `per_recipient_attachments` | Files sent to a single record, to everyone, or one per recipient. |
| `failures` / `skipped_prior` / `status`                      | Run outcome: sends refused, addresses already sent in an earlier run, and whether the run completed or was interrupted. |
| `notes`                                                      | Free-text record of anything notable about the run — including whether it was sent outside the tool. |

### `session` — the one definition

`session` identifies the workshop session a communication belongs to — the session it is *about*, not the day it was sent. Session 1's installation reminders, certificate announcement, and evaluation form are all `session: 1`, whichever day each goes out. A session's communications are treated as closed once its evaluation form has been sent; a message after that point belongs to the *next* session, even when it revisits earlier material. `session` MUST NOT be read as the date sent, the run, or a chronological index.

Canonical type is an integer; a quoted string (`"1"`) is accepted for backward compatibility but should not be written by hand.

------

## Design notes

The decisions worth explaining, and why they went the way they did.

### Validation is shared, not duplicated

`rollup_attendance.py` and `generate_cert.py` both read rosters and both must apply identical name and email rules. Rather than each carrying its own copy, the rules live once in `roster_checks.py` and are imported by both. One source of truth means the two tools cannot silently disagree about what a valid email is.

### Session and tier are derived, not trusted

The real data source is a single accumulating Google Forms export with no session column and no tier field. Session membership comes from timestamp windows; tier comes from counting distinct sessions per email as a set. This is deliberately a first pass to reconcile against the master attendance sheet — the tool flags every ambiguity (a response outside all windows, one name under two emails) rather than inventing an answer.

### Names are stamped verbatim

The registration form asks each person how they want their name to appear. `generate_cert.py` changes nothing but surrounding whitespace and Unicode normalisation form. It does not fix case or spelling, because "correcting" a name is how you put the wrong name on someone's certificate.

### Recipient addresses never reach the report

Sent logs are opened only to count non-blank lines; the addresses are never bound to a variable that reaches the renderer, so they cannot appear in a generated report by accident. The logs themselves are gitignored and never leave the machine.

### The sent log is written *after* the send, not before

The log's only job is idempotency, so its invariant is *an address appears here if and only if a message reached the server*. Recording before the attempt would silently skip a recipient whose send failed; flushing per line means an interrupted run resumes correctly instead of re-sending to everyone.

### `campaigns.jsonl`, not `campaigns.json`

One JSON object per line, append-only. A JSON array would require rewriting the whole file to add one record, and a crash mid-write leaves the closing bracket unwritten, making the *entire* file unparseable. With line-delimited JSON a crash costs at most the record being written.

### A manifest line describes a *run*, not a *campaign*

Because sends are resumable, one campaign can span several runs. Lines are events; `comms_report.py` groups them by `campaign_id` at read time — earliest run for the date, sum of runs for the total. Aggregation is the report's job.

### `--copy-to` is not `--cc`

`--cc`/`--bcc` add headers to *every* message, so a copied address receives one email per recipient — right for an archive mailbox, wrong for a human. `--copy-to` sends exactly one message after the run, carrying the *unrendered* template plus the recipient count and any shared attachments.

### Everything fails before anything sends

Roster parsing reports *all* malformed rows at once. Placeholders are validated against real headers. Every attachment path is resolved and checked. Duplicates are rejected. Only then does the tool ask for confirmation. The alternative — discovering a missing certificate at recipient 43 — leaves a campaign half-sent and a person to apologise to.

### Backward-compatible manifest schema

Early records were hand-written with `sent_at` and `recipient_count` before the run-oriented schema settled. `normalise()` maps legacy field names to canonical ones at the single point where records enter the programme, so old and new lines coexist and the canonical spelling is the only one ever freshly written.

------

## Repository layout

```
├── mail_merge.py          # send personalised bulk email; record each run
├── comms_report.py        # render the manifest into a submittable log
├── rollup_attendance.py   # derive session + tier from the raw export
├── generate_cert.py       # stamp certificate PDFs; enrich the roster
├── roster_checks.py       # shared name/email validation
├── campaigns.jsonl        # campaign manifest, one JSON object per line
├── attachments/           # participant-facing guides distributed in the series
├── data_set/              # public teaching datasets used in the workshop
├── fonts/                 # certificate font (static Montserrat-Regular.ttf)
├── bodies/                # archived message templates — gitignored, local only
└── logs/                  # sent logs — gitignored, contain addresses, local only
```

`bodies/` and `logs/` are excluded from version control: they contain message text and participant email addresses and are retained only on the operator's machine. The certificate templates and the rendered communications reports are likewise kept out of the repository.

------

## Limitations

Stated plainly, because they are the next things to fix.

- **No automated tests.** `mail_merge.py`'s `main()` creates its SMTP connection inline, so there is no seam to inject a fake transport; testing currently needs a live local server. Extracting the send loop into a function taking an already-connected SMTP object is the obvious next refactor. The certificate tools are likewise exercised by hand against real templates rather than by a suite.
- **Communications sent outside the tool need a manual manifest line.** A message sent by hand is recorded with an empty `sent_log`, which the report marks as unverifiable rather than wrong.
- **Plain-text email bodies only.** No HTML multipart alternative.
- **Gmail-oriented defaults.** Host and port are configurable, but the credential guidance assumes an app password.
- **Certificate placement is template-specific.** The stamping constants are measured against one set of templates sharing a fixed geometry; a differently laid-out template needs those constants re-measured.

------

## Requirements

Python 3.12 or later. The communications tools use the standard library only; the certificate tools additionally require `pypdf` and `reportlab`. `aiosmtpd` is needed for local mail testing, not for use.

Credentials are read from the environment, never from a file:

```bash
export WORKSHOP_EMAIL="you@example.com"
export WORKSHOP_PASSWORD="your_app_password"
```

------

## Licence

MIT. See [LICENSE](https://claude.ai/chat/LICENSE).

Written by Jan Ephraim R. Vallente.
