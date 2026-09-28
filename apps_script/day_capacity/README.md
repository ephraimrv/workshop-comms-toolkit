# Day capacity for a Google Form

A Google Apps Script, bound to one registration form, that removes a day from the form's day question once that day has reached its capacity, and closes the form when every day is full.

Written for the USTP Cagayan de Oro workshop (12–14 October 2026): three identical days, 40 on-site seats each, one form.

## How it works

After every submission an installable trigger runs `handleSubmit`, which recounts the answers to the day question across *all* responses, keeps the days still below capacity, and rewrites the question's choices to that list. When no day is left, it sets a closed-form message and stops accepting responses.

- **Recounted, not incremented.** Nothing is stored between runs, so deleting a response (a duplicate, a withdrawn registrant) and running `refresh()` frees that seat.
- **The configured list is the master copy.** Once a day is removed from the form, only `CONFIG.days` still knows it existed, so every label there must match the form character for character. `checkSetup()` refuses to run if the form has a choice the list does not.
- **Never reopens the form by itself.** A closed form may have been closed on purpose (the registration deadline). If a seat is freed after closing, the log says so and a person decides.
- **A lock serialises runs**, so two submissions arriving together cannot both rewrite the choices from stale counts.

## Limits

- **It counts submissions, not confirmed seats.** A duplicate, an ineligible registrant or someone without a laptop still takes a place until their response is deleted and `refresh()` is run. Seats are confirmed by email; this script only stops a full day collecting more registrations.
- **It acts after the fact.** Someone who opened the form before a day filled can still submit that day, so a day can end at 41 or 42.
- **It edits the form while it is live.** Removing a choice does not relabel earlier answers, so the data stays consistent, but the form should say so: *"Days that are full are removed from the list."*
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
8. When the test passes, repeat steps 1–6 on the real form with `capacity: 40`.

After deleting a response in the form's **Responses** tab, run `refresh` by hand.

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

and push with `clasp push`. `.claspignore` limits the push to `Code.js` and `appsscript.json`; the test file must never be pushed, because it uses Node's `require()`. `.clasp.json` is gitignored: it names the script bound to a form that holds participants' data. Command names differ between clasp versions; check `clasp --help` if one is missing.

## Tests

The counting and filtering logic is plain JavaScript with no Google services, so it runs under Node's built-in test runner:

```bash
node --test apps_script/day_capacity/day_capacity.test.js
```

The Apps Script entry points (`listItems`, `checkSetup`, `refresh`, `installTrigger`) can only run inside Apps Script and are tested by hand on a copy of the form, as above.
