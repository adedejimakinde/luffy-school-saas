/**
 * A school's register server, faked for the register page's offline tests.
 *
 * One per host, each with its own register, receipts and signed-in user. It
 * merges a register sent with a base as `attendance.services.take_register()`
 * does (`docs/offline.md` D4): a child the teacher did not change is untouched;
 * a changed child is written only if the school still has what the teacher was
 * shown, is "already" if the school has the teacher's answer, and is otherwise
 * a conflict. A key answers a resend from its receipt, as `sync.receipts.once()`.
 */

export const ST_MARYS = "st-marys.example.ng";
export const GRACE = "grace.example.ng";
export const KEMI = 5;
export const TUNDE = 6;
export const DAY = "2025-09-17";

export function registerSchool(host, { names, signedIn = KEMI, markers = [KEMI, TUNDE] }) {
  const server = {
    host,
    names,
    marks: new Map(), // child -> { status, since }
    taken: false,
    signedIn,
    markers,
    receipts: new Map(),
    puts: [],
    offline: false,
    loseNextAnswer: false,
    refuseWith: null, // [status, detail] for the next PUT
  };
  const reply = (status, body) => ({ status, json: async () => body });
  const ids = names.map((_, i) => i + 1);

  server.office = (statuses, since = "2025-09-17T09:12:00Z") => {
    for (const [sid, status] of Object.entries(statuses)) server.marks.set(Number(sid), { status, since });
    server.taken = true;
  };

  const merge = (body) => {
    const shown = new Set(body.shown_ids);
    const absent = new Set(body.absent_ids);
    const result = { present: [], absent: [], untouched: [], already: [], conflicts: [] };
    const base = body.base;
    const was = (sid) =>
      base.absent_ids.includes(sid) ? "absent" : base.present_ids.includes(sid) ? "present" : null;
    for (const sid of ids.filter((id) => shown.has(id))) {
      const yours = absent.has(sid) ? "absent" : "present";
      const before = was(sid);
      if (yours === before) {
        result.untouched.push(sid);
        continue;
      }
      const mark = server.marks.get(sid);
      const now = mark ? mark.status : null;
      if (now === before) {
        server.marks.set(sid, { status: yours, since: "now" });
        result[yours].push(sid);
      } else if (now === yours) {
        result.already.push(sid);
      } else {
        result.conflicts.push({ student_membership_id: sid, yours, was: before, now, since: mark ? mark.since : null });
      }
    }
    if (result.present.length || result.absent.length) server.taken = true;
    return result;
  };

  server.fetch = async (url, options = {}) => {
    if (server.offline) throw new TypeError("Failed to fetch");
    if (url === "/api/csrf/") return reply(200, { csrf_token: "t" });
    if (server.signedIn === null) return reply(401, { detail: "Sign in.", code: "session_expired" });
    if (!server.markers.includes(server.signedIn)) return reply(403, { detail: "A register is taken by a teacher." });
    if (url === "/api/attendance/where/") {
      return reply(200, {
        term_id: 7,
        term: "2025/2026 First term",
        user_id: server.signedIn,
        classes: [{ id: 11, name: "JSS 1A", level: 1 }],
      });
    }
    const hit = /^\/api\/attendance\/classes\/11\/terms\/7\/([\d-]+)\/$/.exec(url);
    if (!hit) throw new Error(`no stub for ${url}`);
    if (options.method !== "PUT") {
      return reply(200, {
        class_group_id: 11,
        class_group: "JSS 1A",
        term_id: 7,
        term: "2025/2026 First term",
        taken_on: hit[1],
        taken: server.taken,
        rows: ids.map((sid) => ({
          student_membership_id: sid,
          student: names[sid - 1],
          status: server.marks.has(sid) ? server.marks.get(sid).status : null,
        })),
      });
    }
    const body = JSON.parse(options.body);
    server.puts.push({ ...body, as: server.signedIn });
    if (server.refuseWith) {
      const [status, detail] = server.refuseWith;
      server.refuseWith = null;
      return reply(status, { detail });
    }
    let answer = body.key && server.receipts.get(body.key);
    if (!answer) {
      const merged = merge(body);
      answer = [200, {
        class_group_id: 11,
        taken_on: hit[1],
        ...merged,
        appeared: ids.filter((sid) => !body.shown_ids.includes(sid)),
        not_on_the_roster: [],
      }];
      if (body.key) server.receipts.set(body.key, answer);
    }
    if (server.loseNextAnswer) {
      server.loseNextAnswer = false;
      throw new TypeError("Failed to fetch");
    }
    return reply(...answer);
  };
  return server;
}
