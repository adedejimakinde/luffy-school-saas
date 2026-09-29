/**
 * The school's bank account: connect it in three taps.
 *
 * Bank and account number, then **the name the bank holds for it, which the
 * person confirms**, then the one write. Nothing is written by the first two;
 * the server resolves the name again before it writes, so a stale or made-up
 * confirmation is refused with a sentence and the page stays up.
 */

import { REFUSAL, connectAccount, fetchBanks, fetchState, fetchUnmatched, resolveAccount } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "status":
      return states.status(state);
    case "form":
      return states.form(state);
    case "confirm":
      return states.confirm(state);
    case REFUSAL.NOT_ALLOWED:
      return states.notAllowed(state);
    case REFUSAL.WRONG_HOST:
      return states.wrongHost();
    case REFUSAL.EXPIRED:
      return states.signedOut({ portal, expired: true });
    case REFUSAL.SIGNED_OUT:
      return states.signedOut({ portal });
    default:
      return states.broken();
  }
}

const fromRefusal = (answer) => ({ step: answer.refusal, ...(answer.body || {}) });

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const onSchool = root.dataset.onSchool === "yes";
  let state = { step: "loading" };
  let status = null;
  let banks = [];

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const back = (note = null) => {
    state = { ...status, step: "status", note };
  };

  if (onSchool) {
    const answer = await fetchState({ fetchImpl });
    if (answer.ok) {
      // The unmatched payments are read beside the status, and if they cannot
      // be read the page still shows the account: nothing is said about it.
      const unmatched = await fetchUnmatched({ fetchImpl });
      status = { ...answer.body, unmatched: unmatched.ok ? unmatched.body.payments || [] : [] };
      back();
    } else {
      state = fromRefusal(answer);
    }
  } else {
    state = { step: REFUSAL.WRONG_HOST };
  }
  draw();

  root.addEventListener("click", async (event) => {
    const target = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!target) return;
    const action = target.dataset.action;
    if (action === "cancel") {
      back();
    } else if (action === "back") {
      state = { step: "form", banks, values: state.account, note: null };
    } else if (action === "start") {
      const answer = await fetchBanks({ fetchImpl });
      if (answer.ok) {
        banks = answer.body.banks;
        state = { step: "form", banks, values: {}, note: null };
      } else if (answer.refusal) {
        state = fromRefusal(answer);
      } else {
        back(answer.note);
      }
    } else {
      return;
    }
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    if (form.confirm === undefined) {
      // Step one: ask the bank whose account this is. Writes nothing.
      const account = { bank_code: form.bank_code.value, account_number: form.account_number.value.trim() };
      const answer = await resolveAccount(account, { fetchImpl });
      if (answer.ok) {
        const bank = banks.find((b) => b.code === account.bank_code);
        state = {
          step: "confirm",
          account,
          accountName: answer.body.account_name,
          bankName: bank ? bank.name : "",
          note: null,
        };
      } else if (answer.refusal) {
        state = fromRefusal(answer);
      } else {
        state = { step: "form", banks, values: account, note: answer.note };
      }
      draw();
      return;
    }

    // Step two: the only write, of the name the person was shown.
    const answer = await connectAccount(
      { ...state.account, account_name: state.accountName },
      { fetchImpl },
    );
    if (answer.ok) {
      status = { ...answer.body, unmatched: status ? status.unmatched : [] };
      back();
    } else if (answer.refusal) {
      state = fromRefusal(answer);
    } else {
      state = { ...state, note: answer.note };
    }
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("bank");
  if (root) mount(root);
}
