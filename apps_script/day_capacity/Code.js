/**
 * Day capacity for a Google Form registration.
 *
 * Removes a day from the form's day question once that day has
 * CONFIG.capacity responses, and closes the form when every day is
 * full. Counts are recomputed from all responses on every run, so
 * deleting a response (a duplicate, say) and running refresh() frees
 * its seat again.
 *
 * This file holds no participant data. It reads responses inside the
 * form's own Google account and sends nothing anywhere else.
 *
 * Setup (see README.md): paste into the form's Apps Script editor,
 * run listItems() to find the question's ID, fill in CONFIG, run
 * checkSetup(), then run installTrigger() once.
 *
 * @author Jan Ephraim R. Vallente
 * @version 0.1.0
 */

const CONFIG = {
  // ID of the "Which day would you prefer to attend?" question.
  // Run listItems() and copy the number printed next to its title.
  itemId: 0,

  // On-site seats per day.
  capacity: 40,

  // Every day, exactly as written in the form, in display order. This
  // list, not the form, is the master copy: once a day is removed
  // from the form, only this list still knows it existed.
  days: [
    'Day 1: Monday, 12 October',
    'Day 2: Tuesday, 13 October',
    'Day 3: Wednesday, 14 October',
  ],

  // Shown to anyone who opens the form after every day is full.
  closedMessage:
    'Registration is closed: all three days are full. To join the ' +
    'waiting list, please write to jervallente@gmail.com.',
};

// ---------------------------------------------------------------------
// Pure logic: no Google services, so it can be tested outside Apps
// Script (see day_capacity.test.js).
// ---------------------------------------------------------------------

/**
 * Count how many answers name each day.
 *
 * @param {string[]} days every day, in order
 * @param {(string|null)[]} answers one answer per response
 * @return {Object<string, number>} day -> count; unknown answers ignored
 */
function countByDay(days, answers) {
  const counts = {};
  days.forEach((day) => { counts[day] = 0; });
  answers.forEach((answer) => {
    if (Object.prototype.hasOwnProperty.call(counts, answer)) {
      counts[answer] += 1;
    }
  });
  return counts;
}

/**
 * Days still below capacity, in their original order.
 *
 * @param {string[]} days
 * @param {Object<string, number>} counts
 * @param {number} capacity
 * @return {string[]}
 */
function openDays(days, counts, capacity) {
  return days.filter((day) => counts[day] < capacity);
}

/**
 * Choices on the form that are not in the configured list. Any such
 * choice would never be counted, so its day could never fill.
 *
 * @param {string[]} days
 * @param {string[]} formChoices
 * @return {string[]}
 */
function unknownChoices(days, formChoices) {
  return formChoices.filter((choice) => !days.includes(choice));
}

/**
 * True when two lists hold the same strings in the same order.
 *
 * @param {string[]} a
 * @param {string[]} b
 * @return {boolean}
 */
function sameList(a, b) {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

// ---------------------------------------------------------------------
// Apps Script entry points.
// ---------------------------------------------------------------------

/** Log every question's ID, type and title, to fill in CONFIG.itemId. */
function listItems() {
  FormApp.getActiveForm().getItems().forEach((item) => {
    console.log(`${item.getId()}  ${item.getType()}  ${item.getTitle()}`);
  });
}

/** Stop with a clear message if CONFIG does not match the form. */
function checkSetup() {
  const item = dayItem_();
  const onForm = item.getChoices().map((choice) => choice.getValue());
  const unknown = unknownChoices(CONFIG.days, onForm);
  if (unknown.length > 0) {
    throw new Error(
      `These choices on the form are not in CONFIG.days: ${unknown.join(' | ')}`);
  }
  console.log(`OK: "${item.getTitle()}", capacity ${CONFIG.capacity} per day.`);
  refresh();
}

/** Recount and update the form. Run by hand after deleting responses. */
function refresh() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error('Another run is still updating the form; try again.');
  }
  try {
    update_();
  } finally {
    lock.releaseLock();
  }
}

/** Installable trigger target: runs after every submission. */
function handleSubmit(e) {
  refresh();
}

/** Create the submit trigger, replacing any earlier one. Run once. */
function installTrigger() {
  const form = FormApp.getActiveForm();
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'handleSubmit')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('handleSubmit').forForm(form).onFormSubmit().create();
  console.log('Trigger installed: handleSubmit runs after every submission.');
}

// ---------------------------------------------------------------------
// Helpers (a trailing underscore hides them from the Run menu).
// ---------------------------------------------------------------------

function dayItem_() {
  if (!CONFIG.itemId) {
    throw new Error('Set CONFIG.itemId first: run listItems() to find it.');
  }
  const item = FormApp.getActiveForm().getItemById(CONFIG.itemId);
  if (item === null) {
    throw new Error(`No question with ID ${CONFIG.itemId} on this form.`);
  }
  if (item.getType() !== FormApp.ItemType.MULTIPLE_CHOICE) {
    throw new Error('CONFIG.itemId must be a multiple-choice question.');
  }
  return item.asMultipleChoiceItem();
}

function update_() {
  const form = FormApp.getActiveForm();
  const item = dayItem_();

  const answers = form.getResponses().map((response) => {
    const match = response.getItemResponses()
      .find((r) => r.getItem().getId() === CONFIG.itemId);
    return match ? match.getResponse() : null;
  });
  const counts = countByDay(CONFIG.days, answers);
  const open = openDays(CONFIG.days, counts, CONFIG.capacity);
  console.log(`Counts: ${JSON.stringify(counts)}; open: ${open.join(' | ') || 'none'}`);

  if (open.length === 0) {
    // A question cannot have zero choices, so close the form instead
    // and leave the last choice list in place.
    form.setCustomClosedFormMessage(CONFIG.closedMessage);
    form.setAcceptingResponses(false);
    console.log('All days full: form closed.');
    return;
  }

  const current = item.getChoices().map((choice) => choice.getValue());
  if (!sameList(current, open)) {
    item.setChoiceValues(open);
    console.log(`Choices now: ${open.join(' | ')}`);
  }
  if (!form.isAcceptingResponses()) {
    // Never reopen automatically: the form may have been closed on
    // purpose (the registration deadline), not by this script.
    console.log('A day has a free seat, but the form is closed. ' +
                'Reopen it by hand if registration should continue.');
  }
}

// Lets Node's test runner import the pure functions. In Apps Script
// `module` does not exist, so this line does nothing there.
if (typeof module !== 'undefined') {
  module.exports = { countByDay, openDays, unknownChoices, sameList };
}
