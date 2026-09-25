/**
 * Fees: the classes for a term, a class's balances, one child's account, a
 * payment, an undo and a receipt; and (B2) each class's bill, charging the
 * class, and a child's concessions.
 *
 * `?student=` opens an account and `?receipt=` a receipt directly, which is
 * how a reprint is reached from a bookmark.
 *
 * **The form key.** Each payment form and each discount form drawn gets a
 * fresh key (`crypto.randomUUID()`), sent with what was typed. The server
 * records one entry per key, so a double click is one payment or one discount.
 * When the answer is lost — the connection dropped after the request left —
 * the page keeps the key and what was typed, and says so: sending it again
 * cannot record it twice. A concession's grant form works the same way.
 *
 * **A bill is redrawn from the server's answer** after every change, because
 * each bill write answers with the bill as it now stands.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import {
  REFUSAL,
  fetchAccount,
  fetchBill,
  fetchBills,
  fetchBooks,
  fetchClass,
  fetchConcessions,
  fetchNotSent,
  fetchReceipt,
  postBillLine,
  postCharges,
  postConcession,
  postDiscount,
  postPayment,
  postReminders,
  postReversal,
  postRevocation,
  previewReminders,
  putBillLine,
  removeBillLine,
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
    case "bills":
      return states.bills(state) + after;
    case "bill":
      return states.bill(state) + after;
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
  //: One key per form, because each form is its own write: a payment, a
  //: discount and a concession sent under one key would be refused as a
  //: reused form.
  const keys = { payment: newKey(), discount: newKey(), concession: newKey() };
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
    // The reminders that went nowhere are listed under the classes (D10, as
    // decided). Asked beside the books, and a failure there leaves the books.
    const [answer, notSent] = await Promise.all([
      fetchBooks({ termId, fetchImpl }),
      fetchNotSent({ fetchImpl }),
    ]);
    land(answer, (body) => {
      where.termId = body.term_id;
      if (body.term_id === null) return { step: "no-terms" };
      return { step: "books", books: body, notSent: notSent.ok ? notSent.body.children : [] };
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
    const [answer, concessions] = await Promise.all([
      fetchAccount({ studentId, fetchImpl }),
      fetchConcessions({ studentId, fetchImpl }),
    ]);
    // One refusal for both: the routes ask the same question of the same
    // person, so the first read's answer stands for the pair.
    land(answer.ok && !concessions.ok ? concessions : answer, (body) => ({
      step: "account",
      account: body,
      concessions: concessions.body,
      termId: where.termId,
      today,
      ...extra,
    }));
  };
  const showBills = async (termId) => {
    land(await fetchBills({ termId, fetchImpl }), (body) => {
      where.termId = body.term_id;
      return body.term_id === null ? { step: "no-terms" } : { step: "bills", bills: body };
    });
  };
  const showBill = async (classId, extra = {}) => {
    where.classId = classId;
    land(await fetchBill({ classId, termId: where.termId, fetchImpl }), (body) => ({
      step: "bill",
      bill: body,
      ...extra,
    }));
  };
  /**
   * A bill write: the answer is the bill, drawn as it comes back. A lost
   * answer keeps what was typed and says, in `lost`, why sending again is
   * safe for that write.
   *
   * **A 404 here is a line that is no longer there** — another bursar removed
   * it, or this page's own removal landed and its answer did not. The bill is
   * read again rather than the page turned into "not something you can
   * open": if the refusal is real, that read gets it too.
   */
  const billWrite = async (answer, { draftField, draft, done, lost }) => {
    if (answer.ok) {
      state = { step: "bill", bill: answer.body, note: done, noteTone: "done" };
    } else if (answer.refusal === REFUSAL.BROKEN) {
      state = {
        ...state,
        ...(draftField ? { [draftField]: draft } : {}),
        noteTone: "stop",
        note: lost,
      };
    } else if (answer.refusal === REFUSAL.NOT_YOURS) {
      await showBill(where.classId, {
        note: "That line is no longer on this bill. This is the bill as it stands now.",
        noteTone: "stop",
      });
      return;
    } else if (answer.refusal) {
      state = { step: answer.refusal };
    } else {
      state = {
        ...state,
        ...(draftField ? { [draftField]: draft } : {}),
        noteTone: "stop",
        note: answer.body.detail || "That was not saved.",
      };
    }
    draw();
  };
  const showReceipt = async (entryId) => {
    land(await fetchReceipt({ entryId, fetchImpl }), (body) => ({ step: "receipt", receipt: body }));
  };

  if (params.get("receipt")) await showReceipt(Number(params.get("receipt")));
  else if (params.get("student")) await showAccount(Number(params.get("student")));
  else await showBooks(null);

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset) return;
    if (field.dataset.term !== undefined) await showBooks(Number(field.value));
    else if (field.dataset.billsTerm !== undefined) await showBills(Number(field.value));
  });

  /**
   * A write made under a form key: a payment or a discount. Success mints the
   * next key; a lost answer keeps it, and what was typed, so sending again is
   * safe; a sentence from the server keeps what was typed and shows it.
   */
  const keyed = async (intent, draft, send, { done, again, draftField }) => {
    const answer = await send({ ...draft, form_key: keys[intent] });
    if (answer.ok) {
      keys[intent] = newKey();
      await showAccount(where.studentId, { note: done(answer.body), noteTone: "done" });
      return;
    }
    if (answer.refusal === REFUSAL.BROKEN) {
      state = { ...state, [draftField]: draft, noteTone: "stop", note: again };
      draw();
      return;
    }
    if (answer.refusal) {
      state = { step: answer.refusal };
      draw();
      return;
    }
    keys[intent] = newKey();
    state = { ...state, [draftField]: draft, noteTone: "stop", note: answer.body.detail || "That was not saved." };
    draw();
  };

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !["account", "bill"].includes(state.step) || !form.intent) return;
    const intent = form.intent.value;
    if (event.preventDefault) event.preventDefault();

    if (state.step === "bill") {
      if (intent === "add-line") {
        const draft = { description: form.description.value, amount: form.amount.value };
        const answer = await postBillLine({
          classId: where.classId,
          line: { term_id: where.termId, ...draft },
          fetchImpl,
        });
        await billWrite(answer, {
          draftField: "newLineDraft",
          draft,
          done: `Added “${draft.description.trim()}”.`,
          lost: "We could not tell whether that line was added. Send it again — the same line is not added twice.",
        });
        return;
      }
      if (intent === "change-line" && state.changing) {
        const draft = { description: form.description.value, amount: form.amount.value };
        const answer = await putBillLine({ lineId: state.changing, line: draft, fetchImpl });
        await billWrite(answer, {
          draftField: "lineDraft",
          draft,
          done: "Changed. Children already charged keep what they were charged.",
          lost: "We could not tell whether that change was saved. Send it again — saving it twice is the same as once.",
        });
      }
      return;
    }

    if (intent === "payment") {
      const draft = {
        term_id: Number(form.term_id.value),
        amount: form.amount.value,
        method: form.method.value,
        reference: form.reference ? form.reference.value : "",
        effective_on: form.effective_on.value,
      };
      await keyed("payment", draft, (payment) => postPayment({ studentId: where.studentId, payment, fetchImpl }), {
        draftField: "draft",
        done: ({ entry, posted }) =>
          posted
            ? `Payment recorded. Receipt ${entry.receipt_number}.`
            : "That payment was already recorded; nothing new was added.",
        // The request may have landed. Same key, same payment: sending it
        // again records it once whichever way the first one went.
        again: "We could not tell whether that payment was saved. Send it again — it will not be recorded twice.",
      });
      return;
    }

    if (intent === "discount") {
      const draft = { term_id: Number(form.term_id.value), amount: form.amount.value, reason: form.reason.value };
      await keyed("discount", draft, (discount) => postDiscount({ studentId: where.studentId, discount, fetchImpl }), {
        draftField: "discountDraft",
        done: ({ posted }) =>
          posted ? "Discount given. The account below includes it." : "That discount was already given; nothing new was added.",
        again: "We could not tell whether that discount was saved. Send it again — it will not be given twice.",
      });
      return;
    }

    if (intent === "concession") {
      const draft = { amount: form.amount.value, reason: form.reason.value };
      await keyed("concession", draft, (concession) => postConcession({ studentId: where.studentId, concession, fetchImpl }), {
        draftField: "grantDraft",
        done: ({ granted }) =>
          granted
            ? "Concession granted. Each term's bill gives it when the class is charged."
            : "That concession was already granted; nothing new was added.",
        again: "We could not tell whether that concession was saved. Send it again — it will not be granted twice.",
      });
      return;
    }

    if (intent === "revocation" && state.revoking) {
      const answer = await postRevocation({ concessionId: state.revoking, reason: form.reason.value, fetchImpl });
      if (answer.ok) {
        await showAccount(where.studentId, {
          note: "Revoked. No bill will give it from now on; what it already gave stands.",
          noteTone: "done",
        });
        return;
      }
      if (answer.refusal) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      state = { ...state, noteTone: "stop", note: answer.body.detail || "That was not revoked." };
      draw();
      return;
    }

    if (intent === "reversal" && state.reversing) {
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
    if (action === "ask-reminders" && ["books", "class"].includes(state.step)) {
      // Asks first (docs/messaging.md D10): the preview writes nothing, and
      // nothing is sent until "Send them".
      const scope = {
        termId: hit.dataset.term ? Number(hit.dataset.term) : where.termId,
        classId: hit.dataset.class ? Number(hit.dataset.class) : null,
        children: hit.dataset.children ? hit.dataset.children.split(",").map(Number) : null,
      };
      const answer = await previewReminders({ ...scope, fetchImpl });
      if (answer.refusal) state = { step: answer.refusal };
      else if (!answer.ok) {
        state = { ...state, reminding: null, noteTone: "stop", note: answer.body.detail || "Nothing was sent." };
      } else state = { ...state, reminding: { ...answer.body, scope }, note: "", noteTone: "" };
      draw();
      return;
    }
    if (action === "cancel-reminders") {
      state = { ...state, reminding: null };
      draw();
      return;
    }
    if (action === "send-reminders" && state.reminding) {
      const answer = await postReminders({ ...state.reminding.scope, fetchImpl });
      if (answer.refusal) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      const note = answer.body.detail || "Nothing was sent.";
      const noteTone = answer.ok ? "done" : "stop";
      if (state.step === "class") await showClass(where.classId);
      else await showBooks(where.termId);
      if (["books", "class"].includes(state.step)) {
        state = { ...state, note, noteTone };
        draw();
      }
      return;
    }
    if (action === "open-class") return showClass(Number(hit.dataset.class));
    if (action === "open-bills") return showBills(where.termId);
    if (action === "open-bill") return showBill(Number(hit.dataset.class));
    if (action === "back-to-bills") return showBills(where.termId);
    if (action === "change-line" && state.step === "bill") {
      state = { ...state, changing: Number(hit.dataset.line), lineDraft: {}, note: "" };
      draw();
      return;
    }
    if (action === "cancel-line" && state.step === "bill") {
      state = { ...state, changing: null, lineDraft: {} };
      draw();
      return;
    }
    if (action === "remove-line" && state.step === "bill") {
      return billWrite(await removeBillLine({ lineId: Number(hit.dataset.line), fetchImpl }), {
        done: "Removed.",
        lost: "We could not tell whether that line was removed. Press Remove again — if it is gone, the page will say so.",
      });
    }
    if (action === "charge-class" && state.step === "bill") {
      const answer = await postCharges({ classId: where.classId, termId: where.termId, fetchImpl });
      if (answer.ok) return showBill(where.classId, { charged: answer.body });
      if (answer.refusal === REFUSAL.BROKEN) {
        state = {
          ...state,
          charged: null,
          noteTone: "stop",
          note: "We could not tell whether the class was charged. Press it again — nobody is charged twice.",
        };
        draw();
        return;
      }
      if (answer.refusal) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      state = { ...state, charged: null, noteTone: "stop", note: answer.body.detail || "Nobody was charged." };
      draw();
      return;
    }
    if (action === "grant-concession" && state.step === "account") {
      state = { ...state, granting: true, note: "" };
      draw();
      return;
    }
    if (action === "cancel-concession" && state.step === "account") {
      state = { ...state, granting: false, grantDraft: {} };
      draw();
      return;
    }
    if (action === "revoke-concession" && state.step === "account") {
      state = { ...state, revoking: Number(hit.dataset.concession), note: "" };
      draw();
      return;
    }
    if (action === "cancel-revocation" && state.step === "account") {
      state = { ...state, revoking: null };
      draw();
      return;
    }
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
    if (action === "discount" && state.step === "account") {
      state = { ...state, discounting: true, note: "" };
      draw();
      return;
    }
    if (action === "cancel-discount" && state.step === "account") {
      state = { ...state, discounting: false, discountDraft: {} };
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
