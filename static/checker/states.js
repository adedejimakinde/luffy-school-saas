/**
 * Everything the result checker can show, as a pure function of its state.
 *
 * Strings rather than DOM, for `card/states.js`' reason: the refusals are the
 * path nobody demos, and a string can be asserted in `node --test` with no
 * browser.
 *
 * **The card is not drawn here.** `card/render.js` draws it, and `card/states.js`
 * draws the withheld refusal, because the checker is a third reader of the one
 * payload (docs/messaging.md D11) and a second renderer would be a second
 * answer to what a card looks like — the drift `card_payload()` was extracted
 * to stop.
 */

import { esc, waitInWords } from "../web/html.js";
import { card } from "../card/render.js";
import { withheld as heldBack } from "../card/states.js";

/** What the note above the form can be, besides nothing. */
export const NOTE = {
  NOT_OPENED: "not-opened",
  WAIT: "wait",
  BROKEN: "broken",
};

/**
 * The form, with the note from the last answer above it.
 *
 * **The PIN box is always drawn empty**, and the admission number is kept: a
 * family that mistyped the PIN retypes the PIN, and a PIN left sitting in a box
 * on a shared computer is a PIN the next person can read. `autocomplete="off"`
 * on both for the same computer's sake.
 *
 * `inputmode="numeric"` puts a number pad on a phone. It is not
 * `type="number"`, which would drop the spaces the slip prints between the
 * three groups of four and draw a spinner on a twelve-digit PIN; the route
 * takes the spaces out itself.
 */
export function form({ admissionNumber = "", note = null, portal = "" } = {}) {
  return [
    '<section class="state state-form" data-state="form">',
    "<h1>Check a report card</h1>",
    "<p>Type the admission number and the PIN from the result-checker slip ",
    "the school gave you.</p>",
    noteFor(note),
    '<form class="checker-form">',
    '<label for="admission-number">Admission number</label>',
    '<input id="admission-number" name="admission_number" autocomplete="off" ',
    `autocapitalize="characters" spellcheck="false" value="${esc(admissionNumber)}" required>`,
    '<label for="pin">PIN</label>',
    '<input id="pin" name="pin" inputmode="numeric" autocomplete="off" ',
    'spellcheck="false" placeholder="1234 5678 9012" required>',
    '<button type="submit">Open the report card</button>',
    "</form>",
    signIn(portal),
    "</section>",
  ].join("");
}

/**
 * The sentence the last answer left, or nothing.
 *
 * The refusal's sentence is the server's. It is the same for every way the
 * number and the PIN can fail to open a card, and this module must not add a
 * guess at which half was wrong.
 */
function noteFor(note) {
  if (!note) return "";
  if (note.kind === NOTE.WAIT) {
    const wait = waitInWords(note.retryAfter);
    return [
      '<p class="note note-wait" role="alert">',
      esc(note.detail) || "Too many wrong tries. Nothing has been locked.",
      wait ? ` Try again in ${wait}.` : "",
      "</p>",
    ].join("");
  }
  if (note.kind === NOTE.NOT_OPENED) {
    return `<p class="note note-not-opened" role="alert">${
      esc(note.detail) || "That admission number and PIN do not open a report card here."
    }</p>`;
  }
  return [
    '<p class="note note-broken" role="alert">',
    "Something went wrong on our side, and nothing was checked. Please try ",
    "again in a few minutes, and tell the school office if it keeps happening.",
    "</p>",
  ].join("");
}

/**
 * A family with an account does not need a slip: the card is on their sign-in.
 * No portal domain, no sentence — a dead link is worse than none.
 */
function signIn(portal) {
  if (!portal) return "";
  return `<p class="sign-in">Have an account with the school? <a href="//${esc(portal)}/sign-in/">Sign in</a> to see every card for your children.</p>`;
}

/** The card, and the way back to the form. */
export function opened(payload) {
  return card(payload) + another();
}

/**
 * The right PIN, and a card the school is holding. `card/states.js`' own
 * refusal, so it names who to contact in the words the card page uses.
 */
export function withheld(body) {
  return heldBack(body) + another();
}

/**
 * Back to an empty form. The card leaves the page when it is pressed, so a
 * shared computer is not left showing one child's results to the next family.
 */
function another() {
  return '<p class="another"><button type="button" data-action="check-another">Check another card</button></p>';
}
