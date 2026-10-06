/**
 * Edit links for moving registrants between days.
 *
 * Google Forms does not show a response's edit link to the form's
 * editors. This file logs it, so that a registrant who asks to change
 * day can be sent the link to their own response. It changes nothing
 * on the form.
 *
 * This file holds no participant data. MOVE_EMAILS ships with example
 * addresses and logMoveLinks() refuses to run until they are replaced.
 * Replace them in the Apps Script editor only, and put the examples
 * back before any clasp pull or commit.
 *
 * Usage (see README.md): turn on "Allow response editing", fill in
 * MOVE_EMAILS, run logMoveLinks(), send each person only their own
 * link, then turn editing off and run refresh(). Uses CONFIG.itemId
 * from Code.gs.
 *
 * @author Jan Ephraim R. Vallente
 */

/** Addresses to look up. Fill these in the Apps Script editor only. */
const MOVE_EMAILS = ['first@example.com', 'second@example.com', 'third@example.com'];

// ---------------------------------------------------------------------
// Pure logic: no Google services, so it can be tested outside Apps
// Script (see move_links.test.js).
// ---------------------------------------------------------------------

/**
 * Trim and lower-case each address; blank or missing values become ''.
 *
 * @param {(string|null|undefined)[]} values
 * @return {string[]}
 */
function normaliseEmails(values) {
  return values.map((value) => String(value || '').trim().toLowerCase());
}

/**
 * True when any address is still an @example.com placeholder.
 *
 * @param {string[]} emails already normalised
 * @return {boolean}
 */
function hasPlaceholder(emails) {
  return emails.some((email) => email.endsWith('@example.com'));
}

/**
 * Addresses from wanted that appear, whole, among found.
 *
 * @param {string[]} wanted already normalised
 * @param {string[]} found already normalised
 * @return {string[]}
 */
function matchedEmails(wanted, found) {
  return wanted.filter((email) => found.includes(email));
}

// ---------------------------------------------------------------------
// Apps Script entry point.
// ---------------------------------------------------------------------

/** Log the edit link for each address in MOVE_EMAILS, and any not found. */
function logMoveLinks() {
  const wanted = normaliseEmails(MOVE_EMAILS);
  if (hasPlaceholder(wanted)) {
    throw new Error('MOVE_EMAILS still holds example addresses; fill in the real ones first.');
  }
  const seen = new Set();
  FormApp.getActiveForm().getResponses().forEach((response) => {
    const answers = response.getItemResponses();
    const found = normaliseEmails([
      response.getRespondentEmail(),
      ...answers.map((answer) => answer.getResponse()),
    ]);
    const matched = matchedEmails(wanted, found);
    if (matched.length === 0) {
      return;
    }
    matched.forEach((email) => seen.add(email));
    const day = answers.find((answer) => answer.getItem().getId() === CONFIG.itemId);
    console.log(`${matched.join(', ')} | Response ${response.getId()} | ` +
                `${response.getTimestamp()} | ${day ? day.getResponse() : '(no day)'}\n` +
                `EDIT LINK: ${response.getEditResponseUrl()}`);
  });
  const missing = wanted.filter((email) => !seen.has(email));
  if (missing.length > 0) {
    console.log(`NOT FOUND: ${missing.join(', ')}`);
  }
}

// Lets Node's test runner import the pure functions. In Apps Script
// `module` does not exist, so this line does nothing there.
if (typeof module !== 'undefined') {
  module.exports = { MOVE_EMAILS, normaliseEmails, hasPlaceholder, matchedEmails };
}
