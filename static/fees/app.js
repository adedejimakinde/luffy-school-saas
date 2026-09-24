/**
 * Fees: the classes for a term, a class's balances, one child's account, a
 * payment, an undo and a receipt.
 *
 * `?student=` opens an account and `?receipt=` a receipt directly, which is
 * how a reprint is reached from a bookmark.
 *
 * **The form key.** Each payment form drawn gets a fresh key
 * (`crypto.randomUUID()`), sent with the payment. The server records one
 * payment per key, so a double click is one payment. When the answer is lost
 * — the connection dropped after the request left — the page keeps the key
 * and the typed payment, and says so: sending it again cannot record it twice.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import {
  REFUSAL,
  fetchAccount,
  fetchBooks,
  fetchClass,
  fetchReceipt,
  postPayment,
  postReversal,
} from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "books":
      return states.books(state) + after;
    case "class":
      return states.classBalances(state) + after;
    case "account":
      return states.account(state) + after;
    case "receipt":
      return states.receipt(state);
    case "no-terms":
      return states.noTerms() + after;
    case REFUSAL.NOT_YOURS:
      return states.notYours() + after;
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

/** Today in the reader's own calendar, as the date input wants it. */
export function localToday(now = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export async function mount(
  root,
  { fetchImpl = fetch, search = "", newKey = () => crypto.randomUUID(), today = localToday() } = {},
) {
  const portal = root.dataset.portal || "";
  const params = new URLSearchParams(search);
  let state = { step: "loading" };
  let where = { termId: null, classId: null, studentId: null };
  let formKey = newKey();
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  const land = (answer, next) => {
    state = answer.ok ? next(answer.body) : { step: answer.refusal };
    draw();
  };

  if (root.dataset.onSchool !== "yes") {
    state = { step: REFUSAL.WRONG_HOST };
    draw();
    return state;
  }

  const showBooks = async (termId) => {
    const answer = await fetchBooks({ termId, fetchImpl });
    land(answer, (body) => {
      where.termId = body.term_id;
      return body.term_id === null ? { step: "no-terms" } : { step: "books", books: body };
    });
  };
  const showClass = async (classId) => {
    where.classId = classId;
    land(await fetchClass({ classId, termId: where.termId, fetchImpl }), (body) => ({
      step: "class",
      classBalances: body,
    }));
  };
  const showAccount = async (studentId, extra = {}) => {
    where.studentId = studentId;
    land(await fetchAccount({ studentId, fetchImpl }), (body) => ({
      step: "account",
      account: body,
      termId: where.termId,
      today,
      ...extra,
    }));
  };
  const showReceipt = async (entryId) => {
    land(await fetchReceipt({ entryId, fetchImpl }), (body) => ({ step: "receipt", receipt: body }));
  };

  if (params.get("receipt")) await showReceipt(Number(params.get("receipt")));
  else if (params.get("student")) await showAccount(Number(params.get("student")));
  else await showBooks(null);

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.term === undefined) return;
    await showBooks(Number(field.value));
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || state.step !== "account") return;
    if (form.amount) {
      if (event.preventDefault) event.preventDefault();
      const draft = {
        term_id: Number(form.term_id.value),
        amount: form.amount.value,
        method: form.method.value,
        reference: form.reference ? form.reference.value : "",
        effective_on: form.effective_on.value,
      };
      const answer = await postPayment({
        studentId: where.studentId,
        payment: { ...draft, form_key: formKey },
        fetchImpl,
      });
      if (answer.ok) {
        formKey = newKey();
        const { entry, posted } = answer.body;
        await showAccount(where.studentId, {
          note: posted
            ? `Payment recorded. Receipt ${entry.receipt_number}.`
            : "That payment was already recorded; nothing new was added.",
          noteTone: "done",
        });
        return;
      }
      if (answer.refusal === REFUSAL.BROKEN) {
        // The request may have landed. Same key, same payment: sending it
        // again records it once whichever way the first one went.
        state = {
          ...state,
          draft,
          noteTone: "stop",
          note: "We could not tell whether that payment was saved. Send it again — it will not be recorded twice.",
        };
        draw();
        return;
      }
      if (answer.refusal) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      formKey = newKey();
      state = { ...state, draft, noteTone: "stop", note: answer.body.detail || "That was not saved." };
      draw();
      return;
    }
    if (form.reason && state.reversing) {
      if (event.preventDefault) event.preventDefault();
      const answer = await postReversal({ entryId: state.reversing, reason: form.reason.value, fetchImpl });
      if (answer.ok) {
        await showAccount(where.studentId, { note: "Undone. The account below includes it.", noteTone: "done" });
        return;
      }
      if (answer.refusal) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      state = { ...state, noteTone: "stop", note: answer.body.detail || "That was not undone." };
      draw();
    }
  });

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;
    if (action === "open-class") return showClass(Number(hit.dataset.class));
    if (action === "back-to-books") return showBooks(where.termId);
    if (action === "open-account") return showAccount(Number(hit.dataset.student));
    if (action === "back-to-class") return where.classId ? showClass(where.classId) : showBooks(where.termId);
    if (action === "receipt") return showReceipt(Number(hit.dataset.entry));
    if (action === "back-to-account") {
      return where.studentId ? showAccount(where.studentId) : showBooks(where.termId);
    }
    if (action === "print") {
      if (typeof window !== "undefined" && window.print) window.print();
      return;
    }
    if (action === "reverse" && state.step === "account") {
      state = { ...state, reversing: Number(hit.dataset.entry), note: "" };
      draw();
      return;
    }
    if (action === "cancel-reversal" && state.step === "account") {
      state = { ...state, reversing: null };
      draw();
      return;
    }
    if (action !== "sign-out") return;
    const ended = sessionEnded(await signOut({ fetchImpl }));
    if (ended) {
      root.innerHTML = states.signedOut({ portal });
      return;
    }
    signOutFailed = true;
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("fees");
  if (root) mount(root, { search: window.location.search });
}
