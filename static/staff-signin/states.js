/**
 * Every screen the staff sign-in flow can show, as a pure function of a body.
 *
 * One step and five answers, and that is the whole difference from the guardian
 * flow next door. A member of staff proves who they are with something they
 * know, in one request: there is no code, no 202, and nobody to choose between,
 * because `POST /api/login/` either opens a session or refuses.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 *
 * ## What is shared with the guardian flow, and what deliberately is not
 *
 * Shared: `esc()`, and `waitInWords()` — the 429 threshold is the same rule on
 * both doors because it is the same throttle, `guardian_signin.TooManyAttempts`
 * carrying `signin.THROTTLED`.
 *
 * Not shared: the school list. The guardian flow's is a **chooser** — it links
 * each school to `/cards/` on that school's host, and the one-school case skips
 * it entirely. This one links nowhere, for the reason `landed()` gives, so the
 * two have only `esc()` in common and a module holding that would be a module
 * holding nothing.
 */

import { esc, waitInWords } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/**
 * Step one, and the only one. Identifier and password, refusals above the form.
 *
 * **One identifier field, not three**, which is `SignInIn`'s decision rather
 * than this page's: staff reach for their email, and asking somebody to first
 * classify what they are about to type is asking them to know something about
 * our schema. `User.matching_identifier()` resolves all three forms.
 *
 * The password is not echoed back on a refusal and the identifier is. Retyping
 * a password after a typo is expected; retyping an email address because the
 * password was wrong is the page punishing the wrong field.
 */
export function ask({ error = "", identifier = "" } = {}) {
  return [
    '<form class="step step-ask" data-step="ask">',
    "<h1>Staff sign in</h1>",
    "<p>Use the email address, phone number or staff ID your school has for ",
    "you.</p>",
    problem(error),
    '<label for="identifier">Email, phone number or staff ID</label>',
    `<input id="identifier" name="identifier" type="text" autocomplete="username" `,
    `required value="${esc(identifier)}">`,
    '<label for="password">Password</label>',
    '<input id="password" name="password" type="password" ',
    'autocomplete="current-password" required>',
    '<button type="submit">Sign in</button>',
    "</form>",
  ].join("");
}

/**
 * Signed in, and these are the schools. **Named, and not linked.**
 *
 * The link this page has no business drawing is `/cards/`, which is the only
 * page a school's host serves today. It is a *family* surface even for staff:
 * `card_api._children_of()` says "Never staff's roster" and answers with the
 * children the caller is a parent or guardian of, "which for most of them is
 * none". So a teacher sent there lands on "No children on this account… ask the
 * school office to add you as a guardian", which reads as the school's answer to
 * her sign-in. Redirecting her there is wrong; labelling it "Report cards" and
 * making her tap is the same wrong answer with a tap in between.
 *
 * **And the payload cannot tell the two apart.** `SignedInOut.schools` is
 * `SchoolOut` — slug, name, host — built by `api._schools_of()` from
 * `user.schools()`, a distinct `School` query carrying no role and no
 * guardianship. The field it looks like it wants is `roles`, and that is not the
 * question either: `_children_of()` is `role=STUDENT` and (`user=actor` or
 * `guardianships__guardian=actor`), so a PARENT membership with no
 * `Guardianship` rows stands for nobody and a link keyed on the role would be
 * keyed on the near-enough thing. The honest field is a per-school boolean off
 * that same query — answerable from the public schema, since `Membership` and
 * `Guardianship` are both in `SHARED_APPS` — and it is an API change with its own
 * tests rather than something to smuggle in behind a label.
 *
 * So: no link is better than a link to the wrong answer, which is the rule the
 * card page's signed-out state is getting in this same change. Slice 3 gives
 * this page its first destination that is a staff destination — the register —
 * and that is when a link rule gets a second caller and is worth lifting into
 * `web/`.
 *
 * The name is the receipt. A staff-parent may hold two accounts on this
 * platform, and "signed in as" is how she knows which one answered.
 */
export function landed({ full_name = "", schools = [] } = {}) {
  return [
    '<section class="step step-landed" data-step="landed">',
    `<h1>Signed in${full_name ? ` as ${esc(full_name)}` : ""}</h1>`,
    `<p>You can act at ${schools.length === 1 ? "this school" : "these schools"}:</p>`,
    '<ul class="schools">',
    schools.map((school) => `<li>${esc(school.name)}</li>`).join(""),
    "</ul>",
    '<p class="quiet">Your school\'s own pages open on the school\'s own web ',
    "address. Follow the link you were sent, or the one in your browser's ",
    "history.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Signed in, and no school. Not an error — the password was right.
 *
 * Reachable and not rare: `user.schools()` is scoped to `ACCESS_STATUSES`,
 * which is ACTIVE alone, so a **suspended** teacher and an **invited** one who
 * never accepted both sign in successfully and arrive here. It therefore names
 * the invitation, because for one of those two that is the whole answer and it
 * is an action she can take without ringing anybody.
 */
export function nowhere({ full_name = "" } = {}) {
  return [
    '<section class="step step-nowhere" data-step="nowhere">',
    `<h1>Signed in${full_name ? ` as ${esc(full_name)}` : ""}</h1>`,
    "<p>This account is not an active member of staff at any school right ",
    "now.</p>",
    "<p>If a school has just invited you, open the link in the invitation they ",
    "sent — accepting it is what creates the membership. Otherwise the school ",
    "office can tell you where this stands.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Too many tries. The only answer this door gives that varies.
 *
 * `accounts/signin.py` counts the window against the identifier **as typed**,
 * whether or not it resolves to anybody, so being throttled says nothing about
 * whether the account is real — which is what keeps the 429 from being the
 * oracle the 401 refuses to be. The sentence says "nothing has been locked"
 * because that is true: the throttle counts, it does not lock.
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

/** Signed out on purpose. Same host, so the way back is a relative link. */
export function signedOut() {
  return [
    '<section class="step step-signed-out" data-step="signed-out">',
    "<h1>Signed out</h1>",
    "<p>Your session has ended on this browser and on your school's pages.</p>",
    '<p><a href="/staff-sign-in/">Sign in again</a></p>',
    "</section>",
  ].join("");
}

/**
 * Anything the flow cannot explain: a 500, a dead transport, a 403 that
 * survived `postJson`'s one retry with a fresh token.
 *
 * It does not print the underlying error. A teacher reading `SyntaxError:
 * Unexpected token <` learns nothing they can act on.
 */
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
 * `detail` is the API's own string — `signin.REFUSED`, which is the same
 * sentence for no account, a wrong password, a deactivated account and two
 * accounts matching one identifier. The page must not improve on it: splitting
 * those four is how a sign-in route becomes an account-existence oracle, and a
 * page that guessed which had happened would hand back the oracle the API
 * gives up. Never the `code`, which is written for a programmer.
 */
function problem(message) {
  if (!message) return "";
  return `<p class="problem" role="alert">${esc(message)}</p>`;
}
