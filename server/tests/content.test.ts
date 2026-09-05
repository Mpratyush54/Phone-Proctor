import assert from "node:assert/strict";
import test from "node:test";
import { Store } from "../src/store.js";

function setup() {
  const store = new Store("pepper");
  const seeded = store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
  const exam = store.createExam(ctx, "E1", "t", {});
  return { store, ctx, exam };
}

function bankWithContent(store: Store, ctx: Parameters<Store["createBank"]>[0], groups = 2, variantsPerGroup = 3) {
  const bank = store.createBank(ctx, "Bank");
  for (let g = 0; g < groups; g++) {
    const group = store.createGroup(ctx, bank.id, { title: `G${g + 1}`, marks: 2, negativeMarks: 0.5 });
    for (let v = 0; v < variantsPerGroup; v++) {
      store.createVariant(ctx, group.id, {
        stem: `Q${g + 1}.${v + 1}`,
        qtype: "mcq_single",
        options: [
          { label: "a", correct: true },
          { label: "b" },
          { label: "c" },
          { label: "d" },
        ],
      });
    }
  }
  return bank;
}

test("content: bank, groups, variants, publish, bind", () => {
  const { store, ctx, exam } = setup();
  const bank = bankWithContent(store, ctx);
  assert.throws(() => store.publishBank(ctx, "nope"));
  const ver = store.publishBank(ctx, bank.id);
  assert.equal(ver.version, 1);
  const bound = store.bindExamContent(ctx, exam.id, { contentVersionId: ver.id, durationS: 600 });
  assert.equal(bound.content_version_id, ver.id);
  assert.equal(bound.duration_s, 600);
  const cross = store.createOrg("o2", "o2");
  void cross;
  assert.throws(() => store.bindExamContent(ctx, exam.id, { contentVersionId: "nope" }));
});

test("content: variant validation and deprecation", () => {
  const { store, ctx } = setup();
  const bank = store.createBank(ctx, "B");
  const group = store.createGroup(ctx, bank.id, { title: "G" });
  assert.throws(() => store.createVariant(ctx, group.id, { stem: "", options: [{ label: "a" }] }));
  assert.throws(() =>
    store.createVariant(ctx, group.id, { stem: "s", options: [{ label: "only" }] }),
  );
  assert.throws(() =>
    store.createVariant(ctx, group.id, {
      stem: "s",
      options: [
        { label: "a", correct: true },
        { label: "b", correct: true },
      ],
    }),
  );
  const v = store.createVariant(ctx, group.id, {
    stem: "s",
    options: [
      { label: "a", correct: true },
      { label: "b" },
    ],
  });
  assert.equal(store.deprecateVariant(ctx, v.id).deprecated, true);
  assert.throws(() => store.publishBank(ctx, bank.id));
});

test("candidate: code login, one-by-one items, scoring, no-back rule", () => {
  const { store, ctx, exam } = setup();
  const bank = bankWithContent(store, ctx, 2, 2);
  const ver = store.publishBank(ctx, bank.id);
  store.bindExamContent(ctx, exam.id, { contentVersionId: ver.id });
  store.importRoster(ctx, exam.id, [{ student_external_id: "s1", display_name: "Ann" }]);
  const en = [...store.enrollments.values()][0];
  const issued = store.issueCandidateCode(ctx, en.id);
  assert.ok(issued.code.length >= 6);

  const login = store.redeemCandidateCode(issued.code);
  assert.ok(login.grant);
  const grant = store.candidateFromGrant(login.grant);
  assert.equal(grant.sessionId, login.session_id);

  const first = store.nextItem(grant.sessionId);
  assert.equal(first.done, false);
  assert.equal(first.total, 2);
  assert.equal(first.options.length, 4);

  // determinism: same session draws the same variant and option order
  const again = store.nextItem(grant.sessionId);
  assert.equal(again.variant_id, first.variant_id);
  assert.deepEqual(
    (again as { options: { id: string }[] }).options.map((o) => o.id),
    (first as { options: { id: string }[] }).options.map((o) => o.id),
  );

  // wrong option set → incorrect, negative marks
  const wrong = (first as { options: { id: string }[] }).options.filter((_, i) => i > 0).map((o) => o.id);
  assert.deepEqual(store.submitAnswer(grant.sessionId, (first as { variant_id: string }).variant_id, [wrong[0]], ""), {
    accepted: true,
  });
  const stored = [...store.answers.values()].find(
    (a) => a.sessionId === grant.sessionId && a.variantId === (first as { variant_id: string }).variant_id,
  )!;
  assert.equal(stored.correct, false);
  assert.equal(stored.score, -0.5);

  // no-back-navigation (default): re-answer rejected
  assert.throws(() =>
    store.submitAnswer(grant.sessionId, (first as { variant_id: string }).variant_id, [], ""),
  );

  const second = store.nextItem(grant.sessionId);
  assert.equal((second as { position: number }).position, 2);
  // correct answer scores full marks (options arrive shuffled; resolve truth server-side)
  const truth = [...store.qoptions.values()]
    .filter((o) => o.variantId === (second as { variant_id: string }).variant_id && o.correct)
    .map((o) => o.id);
  store.submitAnswer(grant.sessionId, (second as { variant_id: string }).variant_id, truth, "");
  const done = store.nextItem(grant.sessionId);
  assert.equal((done as { done: boolean }).done, true);

  const status = store.candidateStatus(grant.sessionId);
  assert.equal(status.total, 2);
  assert.equal(status.answered, 2);
  assert.equal(status.done, true);

  // staff sees answers with ground truth
  const items = store.sessionAnswers(ctx, grant.sessionId);
  assert.equal(items.length, 2);
  assert.ok(items.every((i) => Array.isArray((i as { correct_option_ids: string[] }).correct_option_ids)));
});

test("candidate: back-navigation allowed when exam permits", () => {
  const { store, ctx, exam } = setup();
  const bank = bankWithContent(store, ctx, 1, 1);
  const ver = store.publishBank(ctx, bank.id);
  store.bindExamContent(ctx, exam.id, { contentVersionId: ver.id, allowBackNavigation: true });
  store.importRoster(ctx, exam.id, [{ student_external_id: "s1", display_name: "Ann" }]);
  const en = [...store.enrollments.values()][0];
  const { code } = store.issueCandidateCode(ctx, en.id);
  const login = store.redeemCandidateCode(code);
  const grant = store.candidateFromGrant(login.grant);
  const item = store.nextItem(grant.sessionId) as { variant_id: string };
  store.submitAnswer(grant.sessionId, item.variant_id, [], "");
  store.submitAnswer(grant.sessionId, item.variant_id, [], "");
});

test("candidate: bad codes and unassigned items rejected", () => {
  const { store } = setup();
  assert.throws(() => store.redeemCandidateCode("NOPE"));
  assert.throws(() => store.candidateFromGrant("bad"));
  assert.throws(() => store.nextItem("missing"));
  assert.throws(() => store.submitAnswer("missing", "v", [], ""));
});

test("worker: expired sessions auto-end", () => {
  const { store, ctx, exam } = setup();
  const bank = bankWithContent(store, ctx, 1, 1);
  const ver = store.publishBank(ctx, bank.id);
  store.bindExamContent(ctx, exam.id, { contentVersionId: ver.id, durationS: 60 });
  store.importRoster(ctx, exam.id, [{ student_external_id: "s1", display_name: "Ann" }]);
  const en = [...store.enrollments.values()][0];
  const { code } = store.issueCandidateCode(ctx, en.id);
  const login = store.redeemCandidateCode(code);
  store.acceptCommand(ctx, login.session_id, "EXAM_START", "k1", {});
  const session = store.sessions.get(login.session_id)!;
  session.startedAt = Date.now() - 61_000;
  const res = store.endExpiredSessions();
  assert.deepEqual(res.ended, [login.session_id]);
  assert.equal(store.sessions.get(login.session_id)!.desired, "ENDED");
  assert.throws(() => store.nextItem(login.session_id));
});
