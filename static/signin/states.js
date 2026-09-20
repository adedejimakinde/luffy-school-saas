/**
 * Every screen the sign-in flow can show, as a pure function of an API body.
 *
 * Four steps and six refusals, and the reason they are strings rather than DOM
 * is the reason `card/states.js` gives: a refusal is the path nobody demos, and
 * a string can be asserted in `node --test` with no browser.
 *
 * ## The four steps are the API's, not a design
 *
 * A guardian signs in with a code on a channel the school verified, so there is
 * no password step and cannot be one. `POST /api/guardian/code/` takes the
 * number; `POST /api/guardian/session/` takes the code and answers one of three
 * ways — a session, a **202 asking whose card this is**, or a refusal. The 202
 * is not an edge case: one handset in a household is the normal Nigerian case
 * this platform is for, and a flow without that step leaves a family stuck
 * half-way in, holding a spent code.
 */

import { esc, waitInWords } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/** Step 1. The number, and no claim about whether we know it. */
export function ask({ error = "", value = "" } = {}) {
  return [
    '<form class="step step-ask" data-step="ask">',
    "<h1>See your child's report card</h1>",
    "<p>Enter the phone number or email address the school has for you. ",
    "We will send you a code.</p>",
    problem(error),
    '<label for="value">Phone number or email</label>',
    `<input id="value" name="value" type="text" autocomplete="username" `,
    `inputmode="tel" required value="${esc(value)}">`,
    '<button type="submit">Send me a code</button>',
    "</form>",
  ].join("");
}

/**
 * Step 2. The code.
 *
 * The sentence deliberately does not say "we have sent you a code", and neither
 * does the API: `guardian_code` answers identically for every value typed, so
 * that a stranger cannot learn whose number is on a guardian record by watching
 * the reply. A page that promised delivery would put back the oracle the route
 * was written to remove.
 */
export function code({ error = "", detail = "" } = {}) {
  return [
    '<form class="step step-code" data-step="code">',
    "<h1>Enter your code</h1>",
    `<p>${esc(detail) || "If that number is on a guardian record, a code is on its way to it."}</p>`,
    problem(error),
    '<label for="code">Your code</label>',
    '<input id="code" name="code" type="text" inputmode="numeric" ',
    'autocomplete="one-time-code" required>',
    '<button type="submit">Sign in</button>',
    '<button type="button" class="again" data-action="restart">Use a different number</button>',
    "</form>",
  ].join("");
}

/**
 * Step 3, the shared handset. 202, and nobody is signed in yet.
 *
 * The code proved the *handset*, not the person: two guardians on one number
 * are two different sets of children. So this asks which of them is here, and
 * the pick goes back to the same route carrying the same code — which is why
 * the page keeps the code rather than clearing it after the first answer.
 *
 * Names are escaped like everything else. They are `full_name` off a user
 * record, typed by whoever created the account.
 */
export function whose({ detail = "", choose = [] } = {}) {
  return [
    '<section class="step step-whose" data-step="whose">',
    "<h1>Who is signing in?</h1>",
    `<p>${esc(detail) || "This number is shared. Choose who you are."}</p>`,
    '<ul class="guardians">',
    choose
      .map(
        (option) =>
          `<li><button type="button" data-guardian="${esc(option.guardian)}">` +
          `${esc(option.full_name)}</button></li>`,
      )
      .join(""),
    "</ul>",
    '<button type="button" class="again" data-action="restart">Start again</button>',
    "</section>",
  ].join("");
}

/**
 * Step 4, only when a guardian has children at more than one school.
 *
 * One school does not reach this page at all — the flow sends that parent
 * straight to their school's host, because a chooser with one option is a
 * question with one answer. More than one is a real question, and it is asked
 * on the portal because that is the only host that can see all of them.
 *
 * A school whose `host` is null is listed without a link rather than dropped.
 * That is a deployment with no primary domain for that school, and a parent
 * being told the name of a school they cannot reach is worse than useless only
 * if it is silent about why.
 *
 * **Signed in, so it carries the sign-out button.** This state and `nowhere()`
 * are the two places the guardian flow stops with a live session on the page,
 * and the handset this flow exists for is one somebody else picks up next. The
 * rule across the platform is the same everywhere: the button is on every page
 * where somebody is signed in.
 */
export function schools({ full_name = "", schools: list = [] } = {}) {
  return [
    '<section class="step step-schools" data-step="schools">',
    `<h1>Welcome${full_name ? `, ${esc(full_name)}` : ""}</h1>`,
    "<p>Your children are at more than one school. Which one?</p>",
    '<ul class="schools">',
    list
      .map((school) =>
        school.host
          ? `<li><a href="//${esc(school.host)}/cards/">${esc(school.name)}</a></li>`
          : `<li>${esc(school.name)} <span class="blank">` +
            "(this school has no web address set up yet — ask the school office)</span></li>",
      )
      .join(""),
    "</ul>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Signed in, and no school to go to.
 *
 * A guardian whose only membership was removed, or whose child left. It is not
 * an error — the credentials were good — so it does not read like one, and it
 * does not offer a link it cannot honour.
 *
 * It does offer the way out, which is the whole of what it can offer: a live
 * session with nowhere to go, on a handset somebody else picks up next, is the
 * one state where a sign-out button is the only useful control on the page.
 */
export function nowhere({ full_name = "" } = {}) {
  return [
    '<section class="step step-nowhere" data-step="nowhere">',
    `<h1>Signed in${full_name ? `, ${esc(full_name)}` : ""}</h1>`,
    "<p>There are no schools on this account yet. If your child has started ",
    "at a school using this platform, ask the school office to add you as ",
    "their guardian.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Too many attempts. The only answer either route gives that varies.
 *
 * `retry_after` is seconds and comes from the API, which counts the window
 * against the value **as typed** — whether or not it resolves to anybody — so
 * that the throttle is not the enumeration oracle the rest of the flow refuses
 * to be.
 *
 * The rounding is `waitInWords()` in `web/html.js` rather than arithmetic
 * written here, because the staff door answers 429 with the same field from the
 * same throttle — `guardian_signin.TooManyAttempts` carries `signin.THROTTLED`
 * — and a threshold kept in two places is a threshold that gets changed in one.
 */
export function throttled({ detail = "", retry_after = null } = {}) {
  const wait = waitInWords(retry_after);
  return [
    '<section class="step step-throttled" data-step="throttled">',
    "<h1>Too many tries</h1>",
    `<p>${esc(detail) || "That is too many attempts for now."}`,
    wait ? ` Try again in ${wait}.` : "",
    "</p>",
    '<button type="button" class="again" data-action="restart">Start again</button>',
    "</section>",
  ].join("");
}

/** Anything the flow cannot explain: a 500, a transport failure, a bad body. */
export function broken() {
  return [
    '<section class="step step-broken" data-step="broken">',
    "<h1>Sign-in is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell your school if it keeps happening.</p>",
    '<button type="button" class="again" data-action="restart">Start again</button>',
    "</section>",
  ].join("");
}

/**
 * One refusal sentence, above the field it is about.
 *
 * Never the code and never the number: `detail` is the API's own sentence and
 * it is written for a parent. A page that added "(code: bad_code)" would be
 * putting a programmer's string in front of somebody trying to read their
 * child's marks.
 */
function problem(message) {
  if (!message) return "";
  return `<p class="problem" role="alert">${esc(message)}</p>`;
}
