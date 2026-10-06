# Day capacity for a Google Form

A Google Apps Script, bound to one registration form, that removes a day from the form's day question once that day has reached its capacity, and closes the form when every day is full.

A second file, `move_links.js`, logs the edit link of a registrant's response, so that a registrant who asks to change day can be moved by editing their own response (see *Moving a registrant to another day*).

Written for the USTP Cagayan de Oro workshop (12–14 October 2026): three identical days, 40 on-site seats each, shared between two forms that each carry their own copy of the script: a public form (`capacity: 33`) and a priority form for nominees (`capacity: 7`).

## How it works

After every submission an installable trigger runs `handleSubmit`, which recounts the answers to the day question across *all* responses, keeps the days still below capacity, and rewrites the question's choices to that list. When no day is left, it sets a closed-form message and stops accepting responses.

- **Recounted, not incremented.** Nothing is stored between runs, so deleting a response (a duplicate, a withdrawn registrant) and running `refresh()` frees that seat.
- **The configured list is the master copy.** Once a day is removed from the form, only `CONFIG.days` still knows it existed, so every label there must match the form character for character. `checkSetup()` refuses to run if the form has a choice the list does not.
- **Sets the closed-form message before closing, and never after.** Google rejects any change to the message while the form is closed ("Invalid data updating form"), so the message is set while the form is still open, and a run that finds the form already closed with every day full changes nothing. A failure to set the message is logged as a warning and does not stop the form closing.
- **Never reopens the form by itself.** A closed form may have been closed on purpose (the registration deadline). If a seat is freed after closing, the log says so and a person decides.
- **A lock serialises runs**, so two submissions arriving together cannot both rewrite the choices from stale counts.

## Limits

- **It counts submissions, not confirmed seats.** A duplicate, an ineligible registrant or someone without a laptop still takes a place until their response is deleted and `refresh()` is run. Seats are confirmed by email; this script only stops a full day collecting more registrations.
- **One capacity for every day.** `CONFIG.capacity` applies to all days alike, so one day cannot be given more seats than another. When the seats are split between two forms, raise one form's capacity only once every day's count on the other form is known.
- **It acts after the fact.** Someone who opened the form before a day filled can still submit that day, so a day can end at 41 or 42.
- **It edits the form while it is live.** Removing a choice does not relabel earlier answers, so the data stays consistent, but the form should say so: *"Days that are full are removed from the list."*
- **The form's Individual view cannot show an answer whose day has been removed.** The response is stored and counted correctly, but once its day has been removed from the question, the Individual view shows the answer greyed out, sometimes under another day's label (observed in testing, 29 September 2026). To find which response to delete, identify it in the linked response sheet (timestamp and email address), then delete it in the form's Individual view by the same timestamp and email address.
- **Delete responses in the form, not in the sheet.** The script counts the form's responses. Deleting a row in the linked sheet leaves the response in the form, so its seat is never freed.
- **Do not add "Go to section based on answer" to the day question.** Rewriting the choices discards any branching set on them.

## Setting it up (in the browser, no tools needed)

Do all of this on a **copy** of the form first, with `capacity: 2`.

1. Open the form in edit mode → ⋮ (More) → **Apps Script**. This creates a script bound to that form.
2. Replace the contents of `Code.gs` with `Code.js` from this folder.
3. **Project Settings** (gear icon) → tick **Show "appsscript.json" manifest file in editor**. Back in the editor, replace `appsscript.json` with the one from this folder. It sets the time zone to Asia/Manila and asks only for access to *this* form and to triggers.
4. Choose `listItems` in the function menu → **Run**. Approve the authorisation prompt (it will warn that the app is unverified: it is your own script; choose *Advanced → Go to …*). Copy the ID printed next to the day question into `CONFIG.itemId`. Check `CONFIG.days` against the form's choices and `CONFIG.capacity`.
5. Run `checkSetup`. It stops with a message if anything does not match, otherwise prints the current counts.
6. Run `installTrigger` **once**. Running it again replaces the trigger rather than adding a second one.
7. Test: submit three responses choosing Day 1. After the second, Day 1 should disappear from the live form; see **Executions** (left sidebar) for each run's log.
8. When the test passes, repeat steps 1–6 on each real form, with its own share of the seats as `capacity`.

After deleting a response in the form's **Responses** tab, run `refresh` by hand.

## Moving a registrant to another day

Response editing is off by default, and a response can be edited only through its own edit link, which Google Forms shows to the person who submitted it but not to the form's editors. `move_links.js` logs that link. It changes nothing on the form.

1. In the Apps Script editor, add a second script file (**+** next to **Files** → **Script**, named `MoveLinks`) and paste in `move_links.js`. It reads `CONFIG.itemId` from `Code.gs`.
2. In the form: **Settings** → **Responses** → turn on **Allow response editing**.
3. In `MOVE_EMAILS`, replace the example addresses with the registrants' addresses and run `logMoveLinks`. Each match logs the address, response ID, timestamp, current day and edit link; an address with no response is listed under `NOT FOUND`. The function refuses to run while any example address remains.
4. Send each registrant only their own link, privately. They open it, change the day and submit.
5. When everyone has edited, turn **Allow response editing** off, which also disables the links, and run `refresh`.
6. Put the example addresses back in `MOVE_EMAILS`.

What the edit link does, observed on the Cagayan de Oro form on 6 October 2026:

- **The registrant edits, not the form's editor.** The form collects verified email addresses. Opened by an editor, a registrant's edit link showed the response and offered to record the *editor's* address with it, so submitting it would have replaced the registrant's address. Each registrant must open their own link while signed in to the account they registered with.
- **An edit changes the existing response.** The linked sheet keeps one row for the person, and that row's timestamp becomes the time of the edit.
- **Anyone holding a link can change that response while editing is on,** so each link goes only to its owner, and editing is turned off as soon as the moves are done.

Whether an edit fires the submit trigger has not been checked; the `refresh` in step 5 recounts either way.

## Keeping the repository and the form in sync (optional)

Copy-and-paste is enough. To push from the repository instead, use [clasp](https://github.com/google/clasp), Google's command-line tool for Apps Script:

```bash
npm install -g @google/clasp      # needs Node.js
clasp login                       # opens a browser to sign in
```

Turn on the Apps Script API once at <https://script.google.com/home/usersettings>. Then, in this folder, create `.clasp.json` with the script's ID (Project Settings → IDs → Script ID):

```json
{"scriptId": "PASTE-THE-SCRIPT-ID", "rootDir": "."}
```

and push with `clasp push`. `.claspignore` limits the push to `Code.js`, `move_links.js` and `appsscript.json`; the test files must never be pushed, because it uses Node's `require()`. `.clasp.json` is gitignored: it names the script bound to a form that holds participants' data. Command names differ between clasp versions; check `clasp --help` if one is missing.

## Tests

The counting, filtering and address-matching logic is plain JavaScript with no Google services, so it runs under Node's built-in test runner:

```bash
node --test 'apps_script/day_capacity/*.test.js'
```

One test also fails if the committed `MOVE_EMAILS` holds anything but example addresses.

The Apps Script entry points (`listItems`, `checkSetup`, `refresh`, `installTrigger`, `logMoveLinks`) can only run inside Apps Script and are tested by hand on a copy of the form, as above.
