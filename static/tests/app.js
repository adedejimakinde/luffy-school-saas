/** The Tests page: banks, questions, tests, approval and preview. (docs/module-notes.md) */

import * as api from "./api.js";
import * as states from "./states.js";
import { fetchClass, printSlips } from "../exam-slips/api.js";
import { saveFile } from "../web/download.js";

const { REFUSAL } = api;

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "tests":
      return states.testsView(state.tests, state);
    case "banks":
      return states.banksView(state.banks);
    case "bank":
      return states.bankView(state.bank, state);
    case "question":
      return states.questionForm(state.bank, state.question, state);
    case "test-form":
      return states.testForm(state.choices, state.test, state);
    case "test":
      return states.testView(state.test, state);
    case "preview":
      return states.previewView(state.testId, state.paper);
    case "sitting":
      return states.sittingView(state.log, state);
    case REFUSAL.NOT_YOURS:
      return states.notYours(state);
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

/** `#bank/3/2` → `["bank", "3", "2"]`. */
export function routeOf(hash) {
  const parts = String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  return parts.length ? parts : ["tests"];
}

const refusal = (answer) => ({ step: answer.refusal, ...answer.body });

/** What a route shows, read from the school. */
export async function load(route, { fetchImpl = fetch } = {}) {
  const [view, a, b, c] = route;
  if (view === "banks") {
    const answer = await api.fetchBanks({ fetchImpl });
    return answer.ok ? { step: "banks", banks: answer.body } : refusal(answer);
  }
  if (view === "bank" || view === "question") {
    const answer = await api.fetchBank({ subjectId: a, level: b, fetchImpl });
    if (!answer.ok) return answer.rejected ? { step: REFUSAL.WRONG_HOST } : refusal(answer);
    if (view === "bank") return { step: "bank", bank: answer.body };
    const question = c === "new" ? null : answer.body.questions.find((q) => String(q.id) === String(c)) || null;
    if (c !== "new" && !question) return { step: REFUSAL.WRONG_HOST };
    return { step: "question", bank: answer.body, question, values: null };
  }
  if (view === "new-test" || view === "edit-test") {
    const list = await api.fetchTests({ fetchImpl });
    if (!list.ok) return refusal(list);
    let test = null;
    if (view === "edit-test") {
      const answer = await api.fetchTest({ testId: a, fetchImpl });
      if (!answer.ok) return answer.rejected ? { step: REFUSAL.WRONG_HOST } : refusal(answer);
      test = answer.body;
    }
    return { step: "test-form", choices: list.body.choices, test };
  }
  if (view === "test") {
    const answer = await api.fetchTest({ testId: a, fetchImpl });
    if (!answer.ok) return answer.rejected ? { step: REFUSAL.WRONG_HOST } : refusal(answer);
    return { step: "test", test: answer.body };
  }
  if (view === "sitting") {
    const answer = await api.fetchSitting({ testId: a, fetchImpl });
    if (!answer.ok) return answer.rejected ? { step: REFUSAL.NOT_YOURS, detail: answer.detail } : refusal(answer);
    return { step: "sitting", log: answer.body };
  }
  if (view === "preview") {
    const answer = await api.fetchPreview({ testId: a, fetchImpl });
    if (!answer.ok) return answer.rejected ? { step: "test", ...(await load(["test", a], { fetchImpl })), detail: answer.detail } : refusal(answer);
    return { step: "preview", testId: a, paper: answer.body };
  }
  const answer = await api.fetchTests({ fetchImpl });
  return answer.ok ? { step: "tests", tests: answer.body } : refusal(answer);
}

/** The question as the form holds it: four options, or five once asked for. */
export function questionFrom(form, count = null) {
  const n = count || (form.option4 ? 5 : 4);
  const options = [];
  for (let i = 0; i < n; i++) options.push(form[`option${i}`] ? form[`option${i}`].value : "");
  const correct = radio(form, "correct");
  return {
    stem: form.stem.value,
    options,
    correct_index: correct === null || correct === "" ? -1 : Number(correct),
    marks: Number(form.marks.value || 0),
    topic: form.topic.value,
    explanation: form.explanation.value,
    image_key: form.image_key.value,
    image_alt: form.image_alt.value,
    version: form.version ? Number(form.version.value) : 0,
  };
}

/** The ticked boxes called `name`. A form without `querySelectorAll` (a test's) gives "1,2". */
function checked(form, name) {
  if (!form.querySelectorAll) return String((form[name] || {}).value || "").split(",").filter(Boolean).map(Number);
  return Array.from(form.querySelectorAll(`input[name="${name}"]`)).filter((i) => i.checked).map((i) => Number(i.value));
}

/** The chosen radio's value, or null. */
function radio(form, name) {
  if (!form.querySelectorAll) return form[name] ? form[name].value : null;
  const hit = Array.from(form.querySelectorAll(`input[name="${name}"]`)).find((i) => i.checked);
  return hit ? hit.value : null;
}
const iso = (value) => (value ? new Date(value).toISOString() : "");

export function testFrom(form) {
  const [subjectId, level] = String(form.bank.value || "-").split("-");
  const on = (name) => Boolean(form[name] && form[name].checked);
  return {
    title: form.title.value,
    subject_id: Number(subjectId),
    level: Number(level),
    class_group_ids: checked(form, "class"),
    question_count: Number(form.question_count.value || 0),
    opens_at: iso(form.opens_at.value),
    closes_at: iso(form.closes_at.value),
    duration: Number(form.duration.value || 0),
    late_window: Number(form.late_window.value),
    shuffle_questions: on("shuffle_questions"),
    shuffle_options: on("shuffle_options"),
    can_go_back: on("can_go_back"),
    grid: on("grid"),
    calculator: on("calculator"),
    require_pin: on("require_pin"),
  };
}

/** An admission number as one would type it twice: trimmed, one space, any case. */
export const admissionKey = (typed) => String(typed || "").trim().replace(/\s+/g, " ").toLowerCase();

export async function mount(root, { fetchImpl = fetch, location = window.location, save = saveFile } = {}) {
  const portal = root.dataset.portal || "";
  let state = await load(routeOf(location.hash), { fetchImpl });
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();
  const go = (hash) => {
    if (location.hash === hash) return route();
    location.hash = hash;
    return null;
  };
  const route = async () => {
    state = await load(routeOf(location.hash), { fetchImpl });
    draw();
    if (root.scrollIntoView) root.scrollIntoView({ block: "start" });
  };
  if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("hashchange", route);

  /** A refusal for the page, or a sentence on this view. */
  const answered = (result, next) => {
    if (result.ok) return next(result.body);
    if (result.refusal) state = refusal(result);
    else state = { ...state, detail: result.detail, confirming: null };
    draw();
    return null;
  };

  /** The PDF for a class or one student, then the log again so "last issued" is the school's own. */
  let printing = false;
  const printSlip = async (classId, mode = {}) => {
    if (printing) return;
    printing = true;
    try {
      const result = await printSlips({ classGroupId: classId, ...mode, fetchImpl });
      if (!result.ok) {
        if (result.refusal) state = refusal(result);
        else state = { ...state, confirming: null, slips: { [classId]: { kind: "note", text: result.detail || "That slip could not be printed." } } };
        return draw();
      }
      save(result.blob, result.filename);
      const said = mode.onlyMissing
        ? `Printed. Saved as ${result.filename}. Slips already handed out still work.`
        : mode.studentId
          ? `Printed. Saved as ${result.filename}. Their earlier slip no longer works.`
          : `Printed. Saved as ${result.filename}. Hand the slips out; every earlier slip for this class no longer works.`;
      const again = await api.fetchSitting({ testId: state.log.test_id, fetchImpl });
      state = { step: "sitting", log: again.ok ? again.body : state.log, slips: { [classId]: { kind: "done", text: said } } };
      draw();
    } finally {
      printing = false;
    }
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit || hit.tagName === "INPUT" || hit.tagName === "SELECT") return;
    const { action } = hit.dataset;
    const slip = /^slip-(missing|reissue)-(\d+)$/.exec(action);
    if (slip && state.step === "sitting") {
      return printSlip(Number(slip[2]), slip[1] === "missing" ? { onlyMissing: true } : { replace: true });
    }
    if (action.startsWith("ask-")) {
      state = { ...state, confirming: action.slice(4), detail: "", done: "", slips: {} };
      draw();
      // A confirmation that cancels something opens on Cancel.
      const safe = root.querySelector && root.querySelector("[data-default]");
      if (safe && safe.focus) safe.focus();
      return null;
    }
    if (action === "keep") {
      state = { ...state, confirming: null };
      return draw();
    }
    if (action === "no-picture") {
      const form = root.querySelector('form[data-form="question"]');
      state = { ...state, values: { ...questionFrom(form), picture: null, image_key: "", image_alt: "" } };
      return draw();
    }
    if (state.step === "question" && (action === "retire" || action === "delete-question")) {
      const call = action === "retire" ? api.retireQuestion : api.deleteQuestion;
      const result = await call({ questionId: state.question.id, fetchImpl });
      return answered(result, () => go(`#bank/${state.bank.subject_id}/${state.bank.level}`));
    }
    if (state.step === "sitting" && action === "set-code") {
      const result = await api.setCode({ testId: state.log.test_id, fetchImpl });
      return answered(result, (log) => {
        state = { step: "sitting", log, code: log.code, done: "" };
        draw();
      });
    }
    if (state.step === "test") {
      const testId = state.test.id;
      if (action === "delete-test") return answered(await api.deleteTest({ testId, fetchImpl }), () => go("#"));
      const moves = { submit: "submit", withdraw: "withdraw", approve: "approve" };
      if (moves[action]) {
        const result = await api.moveTest({ testId, act: moves[action], fetchImpl });
        const said = { submit: "Sent for approval. Its questions are drawn and copied in.", withdraw: "Withdrawn. It is a draft again.", approve: "Approved. It opens as set." }[action];
        return answered(result, (test) => {
          state = { step: "test", test, done: said };
          draw();
        });
      }
    }
    return null;
  });

  root.addEventListener("change", async (event) => {
    const input = event.target;
    const action = input && input.dataset ? input.dataset.action : "";
    if (state.step === "question" && action === "count") {
      const form = input.form;
      const values = { ...questionFrom(form), picture: (state.values || {}).picture ?? (state.question || {}).picture ?? null };
      const options = values.options.slice(0, Number(input.value));
      while (options.length < Number(input.value)) options.push("");
      if (values.correct_index >= options.length) values.correct_index = -1;
      state = { ...state, values: { ...values, options } };
      draw();
    } else if (state.step === "question" && action === "picture" && input.files && input.files[0]) {
      const form = input.form;
      const typed = questionFrom(form);
      const result = await api.uploadPicture({ subjectId: state.bank.subject_id, level: state.bank.level, file: input.files[0], fetchImpl });
      if (!result.ok) return answered(result, () => null);
      state = { ...state, detail: "", values: { ...typed, picture: result.body, image_key: result.body.key } };
      draw();
    } else if (state.step === "test-form" && action === "bank") {
      const form = input.form;
      const kept = testFrom(form);
      state = { ...state, choice: input.value, test: state.test ? { ...state.test, ...kept, class_group_ids: [] } : null };
      draw();
      const again = root.querySelector('form[data-form="test"]');
      if (again) again.title.value = kept.title;
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset) return;
    if (event.preventDefault) event.preventDefault();
    const kind = form.dataset.form;
    if (kind === "slip-one" && state.step === "sitting") {
      const classId = Number(form.dataset.class);
      const say = (text) => {
        state = { ...state, slips: { [classId]: { kind: "note", text } } };
        draw();
      };
      const wanted = admissionKey(form.admission.value);
      if (!wanted) return say("Type the student's admission number.");
      const roster = await fetchClass({ classGroupId: classId, fetchImpl });
      if (!roster.ok) {
        if (roster.refusal) {
          state = refusal(roster);
          return draw();
        }
        return say((roster.body || {}).detail || "That class could not be read.");
      }
      const student = roster.body.students.find((s) => admissionKey(s.admission_number) === wanted);
      if (!student) return say(`No student with admission number ${form.admission.value.trim()} is in ${roster.body.name} this term.`);
      return printSlip(classId, { studentId: student.id });
    }
    if (kind === "question") {
      const question = questionFrom(form);
      const { bank } = state;
      const result = state.question
        ? await api.editQuestion({ questionId: state.question.id, question, fetchImpl })
        : await api.addQuestion({ subjectId: bank.subject_id, level: bank.level, question, fetchImpl });
      if (!result.ok && result.rejected) {
        const picture = (state.values || {}).picture ?? (state.question || {}).picture ?? null;
        state = { ...state, detail: result.detail, values: { ...question, picture: question.image_key ? picture : null } };
        draw();
        return;
      }
      answered(result, () => go(`#bank/${bank.subject_id}/${bank.level}`));
    } else if (kind === "test") {
      const test = testFrom(form);
      const result = state.test ? await api.updateTest({ testId: state.test.id, test, fetchImpl }) : await api.createTest({ test, fetchImpl });
      if (!result.ok && result.rejected) {
        state = { ...state, detail: result.detail };
        draw();
        return;
      }
      answered(result, (saved) => go(`#test/${saved.id}`));
    } else if (kind === "send-back") {
      const result = await api.moveTest({ testId: state.test.id, act: "send-back", note: form.note.value, fetchImpl });
      answered(result, (test) => {
        state = { step: "test", test, done: "Sent back to its teacher, with your reason." };
        draw();
      });
    } else if (state.step === "sitting" && (kind === "control" || kind === "extra" || kind === "retake")) {
      const testId = state.log.test_id;
      let result;
      let said;
      if (kind === "control") {
        const opening = form.dataset.kind === "open";
        result = await api.controlSitting({
          testId, classId: form.dataset.class, kind: form.dataset.kind, reason: form.reason.value,
          endAttempts: Boolean(form.end_attempts && form.end_attempts.checked), fetchImpl,
        });
        said = opening ? "Opened. Its students can start now. This is logged." : "Closed. Nobody new can start. This is logged.";
      } else if (kind === "extra") {
        result = await api.giveExtraTime({ testId, studentId: form.dataset.student, minutes: Number(form.minutes.value || 0), reason: form.reason.value, fetchImpl });
        said = "Extra time given. Their timer grows when their computer next hears from the school.";
      } else {
        result = await api.allowRetake({ testId, studentId: form.dataset.student, reason: form.reason.value, fetchImpl });
        said = "Retake allowed. They sign in again with the code and their slip.";
      }
      answered(result, (log) => {
        state = { step: "sitting", log, done: said };
        draw();
      });
    } else if (kind === "classes") {
      const result = await api.changeClasses({ testId: state.test.id, classGroupIds: checked(form, "class"), fetchImpl });
      answered(result, (test) => {
        state = { step: "test", test, done: "Classes changed. The change is logged." };
        draw();
      });
    }
  });

  return { state: () => state, route };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("tests");
  if (root) {
    // An enhancement: if it cannot load, each select opens the system menu.
    import("../web/dates.js").then((dates) => dates.enhanceDates(root), () => {});
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
