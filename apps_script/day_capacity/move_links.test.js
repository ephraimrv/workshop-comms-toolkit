const test = require('node:test');
const assert = require('node:assert/strict');
const {
  MOVE_EMAILS, normaliseEmails, hasPlaceholder, matchedEmails,
} = require('./move_links.js');

test('normaliseEmails trims, lower-cases and blanks missing values', () => {
  assert.deepEqual(normaliseEmails([' Ana@X.org ', null, undefined, '']), ['ana@x.org', '', '', '']);
});

test('normaliseEmails turns a checkbox answer (array) into a string, not a match', () => {
  assert.deepEqual(normaliseEmails([['a@x.org', 'b@x.org']]), ['a@x.org,b@x.org']);
});

test('hasPlaceholder catches any example address, in any case', () => {
  assert.equal(hasPlaceholder(normaliseEmails(['real@ustp.edu.ph', 'First@Example.com'])), true);
  assert.equal(hasPlaceholder(normaliseEmails(['real@ustp.edu.ph'])), false);
});

test('matchedEmails needs a whole-address match, not a substring', () => {
  const found = normaliseEmails(['ana.extra@x.org', 'Ben@x.org ']);
  assert.deepEqual(matchedEmails(normaliseEmails(['ana@x.org', 'ben@x.org']), found), ['ben@x.org']);
});

test('matchedEmails ignores a blank respondent email', () => {
  assert.deepEqual(matchedEmails(['ana@x.org'], normaliseEmails(['', 'other'])), []);
});

test('the committed MOVE_EMAILS holds only example addresses', () => {
  const real = normaliseEmails(MOVE_EMAILS).filter((email) => !email.endsWith('@example.com'));
  assert.deepEqual(real, [], 'put the example addresses back before committing');
});
