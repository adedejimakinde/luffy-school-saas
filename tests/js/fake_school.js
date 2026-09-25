/**
 * A school's gradebook server, faked for the marking page's tests.
 *
 * One per host, each with its own marks, versions, receipts and signed-in
 * user, so that a test can run the same story at two schools and see that
 * neither school's writes reach the other. It judges a save as
 * `set_score_as()` does, in the same order, and nothing the device could judge
 * for it; it answers a replayed key from its receipt as `sync.receipts.once()`
 * does.
 */

export const ST_MARYS = "st-marys.example.ng";
export const GRACE = "grace.example.ng";
export const KEMI = 5;
export const TUNDE = 6;

const ROSTER = [
  { id: 1, name: "Ada Obi" },
  { id: 2, name: "Emeka Nwosu" },
];

const WHERE = {
  term_id: 7,
  term: "2025/2026 First term",
  assessments: [{ id: 3, name: "First CA", subject: "Mathematics", max_score: 20 }],
  classes: [{ id: 11, name: "JSS 1A", level: 1 }],
};

function sheetOf(server) {
  return {
    assessment_id: 3,
    assessment: "First CA",
    subject: "Mathematics",
    term: WHERE.term,
    class_group_id: 11,
    class_group: "JSS 1A",
    max_score: server.maxScore,
    locked: server.locked,
    locked_reason: server.locked ? "This sheet has been submitted." : null,
    rows: server.roster.map(({ id, name }) => {
      const mark = server.marks.get(id);
      return {
        student_membership_id: id,
        student: name,
        value: mark ? mark.value : null,
        version: mark ? mark.version : null,
        max_score: server.maxScore,
        total: { scored: mark ? mark.value : 0, available: mark ? server.maxScore : 0, marked: mark ? 1 : 0 },
      };
    }),
  };
}

export function school(
  host,
  { marks = {}, locked = false, maxScore = 20, signedIn = KEMI, markers = [KEMI, TUNDE], roster = ROSTER } = {},
) {
  const server = {
    host,
    marks: new Map(Object.entries(marks).map(([id, mark]) => [Number(id), { ...mark }])),
    locked,
    maxScore,
    signedIn,
    markers,
    receipts: new Map(),
    roster,
    puts: [],
    loseNextAnswer: false,
    offline: false,
    // Authority removed between the drain asking who is signed in and the
    // write arriving: the only way a write itself meets a 403, since `/where/`
    // refuses a non-marker first.
    revokeBeforeNextPut: false,
  };

  const reply = (status, body) => ({ status, json: async () => body });

  const judge = (id, body) => {
    if (server.signedIn === null) return [401, { detail: "Sign in.", code: "session_expired" }];
    if (!server.markers.includes(server.signedIn)) return [403, { detail: "Your account can no longer enter marks here." }];
    const current = server.marks.get(id) || null;
    const expected = body.expected_version === undefined ? null : body.expected_version;
    if ((current ? current.version : null) !== expected) {
      return [409, { detail: "Changed meanwhile.", current: current && { student_membership_id: id, ...current } }];
    }
    if (server.locked) return [423, { detail: "This sheet has been submitted. Ask for it to be sent back." }];
    if (body.value < 0 || body.value > server.maxScore) {
      return [422, { detail: `${body.value} is more than the ${server.maxScore} this is out of.` }];
    }
    const mark = { value: body.value, version: current ? current.version + 1 : 1, by: server.signedIn };
    server.marks.set(id, mark);
    return [200, { student_membership_id: id, value: mark.value, version: mark.version }];
  };

  const refusal = () => {
    if (server.signedIn === null) return reply(401, { detail: "Sign in.", code: "session_expired" });
    if (!server.markers.includes(server.signedIn)) return reply(403, { detail: "Marking is done by a teacher." });
    return null;
  };

  server.fetch = async (url, options = {}) => {
    if (server.offline) throw new TypeError("Failed to fetch");
    if (url === "/api/csrf/") return reply(200, { csrf_token: "t" });
    if (url === "/api/gradebook/where/") {
      return refusal() || reply(200, { ...WHERE, user_id: server.signedIn });
    }
    if (url === "/api/gradebook/assessments/3/sheet/?class_group_id=11") {
      return refusal() || reply(200, sheetOf(server));
    }
    const hit = /^\/api\/gradebook\/assessments\/(\d+)\/scores\/(\d+)\/$/.exec(url);
    if (!hit || options.method !== "PUT") throw new Error(`no stub for ${url}`);
    const id = Number(hit[2]);
    const body = JSON.parse(options.body);
    if (server.revokeBeforeNextPut) {
      server.revokeBeforeNextPut = false;
      server.markers = [];
    }
    server.puts.push({ id, ...body, as: server.signedIn });

    let answer;
    const receipt = body.key && server.receipts.get(body.key);
    if (receipt) {
      answer = receipt;
    } else {
      answer = judge(id, body);
      if (body.key && answer[0] === 200) server.receipts.set(body.key, answer);
    }
    if (server.loseNextAnswer) {
      server.loseNextAnswer = false;
      throw new TypeError("Failed to fetch");
    }
    return reply(...answer);
  };
  return server;
}

