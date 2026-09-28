// Tests for the pure functions in Code.js. Run with: node --test
// No Google services are touched; the Apps Script entry points are
// tested by hand on a copy of the form (see README.md).

const test = require('node:test');
const assert = require('node:assert/strict');
const { countByDay, openDays, unknownChoices, sameList } = require('./Code.js');

const DAYS = ['Day 1', 'Day 2', 'Day 3'];

test('counts each day and ignores blanks and unknown answers', () => {
  const counts = countByDay(DAYS, ['Day 1', 'Day 3', 'Day 1', null, 'Day 9']);
  assert.deepEqual(counts, { 'Day 1': 2, 'Day 2': 0, 'Day 3': 1 });
});

test('an answer spelled differently from CONFIG is not counted', () => {
  const counts = countByDay(DAYS, ['Day 1 ', 'day 1']);
  assert.equal(counts['Day 1'], 0);
});

test('a day at capacity is removed; order is kept', () => {
  const counts = { 'Day 1': 2, 'Day 2': 1, 'Day 3': 0 };
  assert.deepEqual(openDays(DAYS, counts, 2), ['Day 2', 'Day 3']);
});

test('a day over capacity (late submissions) stays removed', () => {
  const counts = { 'Day 1': 3, 'Day 2': 0, 'Day 3': 0 };
  assert.deepEqual(openDays(DAYS, counts, 2), ['Day 2', 'Day 3']);
});

test('a day one below capacity stays open', () => {
  const counts = { 'Day 1': 1, 'Day 2': 1, 'Day 3': 1 };
  assert.deepEqual(openDays(DAYS, counts, 2), DAYS);
});

test('every day full gives no open days', () => {
  const counts = { 'Day 1': 2, 'Day 2': 2, 'Day 3': 2 };
  assert.deepEqual(openDays(DAYS, counts, 2), []);
});

test('a freed seat reopens its day in its original place', () => {
  const counts = { 'Day 1': 1, 'Day 2': 2, 'Day 3': 2 };
  assert.deepEqual(openDays(DAYS, counts, 2), ['Day 1']);
});

test('form choices missing from CONFIG are reported', () => {
  assert.deepEqual(unknownChoices(DAYS, ['Day 1', 'Day 2 ']), ['Day 2 ']);
  assert.deepEqual(unknownChoices(DAYS, ['Day 3']), []);
});

test('sameList compares order as well as content', () => {
  assert.equal(sameList(['a', 'b'], ['a', 'b']), true);
  assert.equal(sameList(['a', 'b'], ['b', 'a']), false);
  assert.equal(sameList(['a'], ['a', 'b']), false);
});
