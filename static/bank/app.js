/**
 * The school's bank account: connect it in three taps.
 *
 * Bank and account number, then **the name the bank holds for it, which the
 * person confirms**, then the one write. Nothing is written by the first two;
 * the server resolves the name again before it writes, so a stale or made-up
 * confirmation is refused with a sentence and the page stays up.
 */

import {
  REFUSAL,
  connectAccount,
  fetchBanks,
  fetchClassChildren,
  fetchClasses,
  fetchState,
  fetchUnmatched,
  placePayment,
  resolveAccount,
} from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "status":
      return states.status(state);
    case "form":
      return states.form(state);
    case "confirm":
      return states.confirm(state);
    case "place":
      return states.place(state);
    case "place-confirm":
      return states.placeConfirm(state);
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
  // The list of payments that could not be matched, and whether this login may place them.
  const readUnmatched = async () => {
    const answer = await fetchUnmatched({ fetchImpl });
    return {
      unmatched: answer.ok ? answer.body.payments || [] : [],
      mayPlace: answer.ok ? Boolean(answer.body.may_place) : false,
    };
  };

  if (onSchool) {
    const answer = await fetchState({ fetchImpl });
    if (answer.ok) {
      // The unmatched payments are read beside the status, and if they cannot
      // be read the page still shows the account: nothing is said about it.
      status = { ...answer.body, ...(await readUnmatched()) };
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
    if (action === "place") {
      // Choosing a child writes nothing: it reads the classes the bursar already reads.
      const payment = (status.unmatched || []).find((p) => String(p.payment_id) === target.dataset.payment);
      const classes = await fetchClasses({ fetchImpl });
      if (!payment) {
        back("That payment is not on the list any more.");
      } else if (classes.refusal && classes.refusal !== REFUSAL.BROKEN) {
        state = fromRefusal(classes);
      } else if (!classes.ok) {
        back("The classes could not be read. Try again.");
      } else {
        state = {
          step: "place",
          payment,
          termId: classes.body.term_id,
          classes: classes.body.classes || [],
          classId: null,
          children: [],
          childId: null,
          note: null,
        };
      }
    } else if (action === "cancel-place") {
      back();
    } else if (action === "back-to-pick") {
      state = { ...state, step: "place", note: null };
    } else if (action === "cancel") {
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

  // The class and the child, when placing a payment. Choosing a class reads its children.
  root.addEventListener("change", async (event) => {
    const field = event.target && event.target.closest ? event.target.closest("[data-field]") : null;
    if (!field || state.step !== "place") return;
    if (field.dataset.field === "class") {
      const classId = Number(field.value) || null;
      let children = [];
      if (classId) {
        const answer = await fetchClassChildren({ classId, termId: state.termId, fetchImpl });
        if (answer.ok) children = answer.body.children || [];
        else if (answer.refusal && answer.refusal !== REFUSAL.BROKEN) {
          state = fromRefusal(answer);
          draw();
          return;
        } else {
          state = { ...state, classId, children: [], childId: null, note: "That class could not be read. Try again." };
          draw();
          return;
        }
      }
      state = { ...state, classId, children, childId: null, note: null };
    } else if (field.dataset.field === "child") {
      state = { ...state, childId: Number(field.value) || null, note: null };
    }
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    if (state.step === "place") {
      // Review: which child. Writes nothing.
      const childId = Number(form.child && form.child.value) || state.childId;
      if (!childId) {
        state = { ...state, note: "Choose the class and then the child." };
      } else {
        const child = state.children.find((c) => c.student_membership_id === childId) || {};
        state = { ...state, step: "place-confirm", childId, child, note: null };
      }
      draw();
      return;
    }
    if (state.step === "place-confirm") {
      // The only write: the child, and the amount and reference as they were read back.
      const answer = await placePayment({
        paymentId: state.payment.payment_id,
        studentId: state.childId,
        amountKobo: state.payment.amount_kobo,
        reference: state.payment.reference,
        fetchImpl,
      });
      if (answer.ok) {
        status = { ...status, ...(await readUnmatched()) };
        back(`Placed on ${answer.body.placed.student}. It is in their account now.`);
      } else if (answer.refusal) {
        state = fromRefusal(answer);
      } else {
        state = { ...state, note: answer.note };
      }
      draw();
      return;
    }

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
      status = { ...status, ...answer.body };
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
