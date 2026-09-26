// Engine and payment tests for Yogii Risk Web.  Run: node --test tests/engine.test.js
// Loads src/app.js through the __YOGII_TEST__ hook with minimal browser stubs.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const MODEL = JSON.parse(fs.readFileSync(path.join(ROOT, 'models', 'yogii_risk_model.json'), 'utf8'));
const APP_SRC = fs.readFileSync(path.join(ROOT, 'src', 'app.js'), 'utf8');

function loadApp(model) {
  const store = new Map();
  const sandbox = {
    __YOGII_TEST__: { model },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k)
    },
    crypto: globalThis.crypto,
    TextEncoder, Intl, Math, Date, JSON, console
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(APP_SRC, sandbox, { filename: 'app.js' });
  return sandbox.__YOGII_TEST__.api;
}

const api = loadApp(MODEL);
const T0 = new Date(2026, 8, 26, 14, 0, 0).getTime();
let clock = T0;
api.setNow(() => clock);

async function freshDb() {
  clock = T0;
  return api.seedDb({ fastHash: true });
}

const user = (db, upi) => api.findUserByUpi(db, upi);
// values created inside the vm sandbox have that realm's prototypes; compare as plain data
const plain = (x) => JSON.parse(JSON.stringify(x));
let keyN = 0;

/** Create + assess, and if allowed approve, verify and authorise (demo PIN). */
function pay(db, from, to, amount, controls = {}, opts = {}) {
  const s = user(db, from);
  const r = api.resolveRecipient(db, to, s.id).recipient;
  const p = api.createPayment(db, { senderId: s.id, recipient: r, amount, controls: { outcome: 'success', ...controls }, key: opts.key || 'k' + (++keyN) });
  if (p.status === 'DRAFT') api.assessPayment(db, p);
  if (opts.stopAfterRisk) return p;
  if (p.status !== 'BLOCKED') {
    api.approvePayment(p);
    if (p.status === 'NEEDS_VERIFICATION') api.verifyPayment(p);
    const res = api.authorizePayment(db, p, '1234');
    assert.ok(res.ok, 'demo PIN accepted');
  }
  clock += 10 * 60 * 1000;
  return p;
}

// ------------------------------------------------------------------ bands
test('band boundaries', () => {
  assert.equal(api.bandFor(0), 'LOW');
  assert.equal(api.bandFor(29), 'LOW');
  assert.equal(api.bandFor(30), 'MEDIUM');
  assert.equal(api.bandFor(59), 'MEDIUM');
  assert.equal(api.bandFor(60), 'HIGH');
  assert.equal(api.bandFor(84), 'HIGH');
  assert.equal(api.bandFor(85), 'VERY_HIGH');
  assert.equal(api.bandFor(100), 'VERY_HIGH');
});

// ------------------------------------------------------------------ model file
test('model file shape and feature lists', () => {
  assert.equal(MODEL.format, 'yogii-risk-model');
  assert.equal(MODEL.synthetic, true);
  assert.deepEqual(MODEL.features.amount, ['log_amount', 'amount_ratio', 'amount_z', 'share_of_balance', 'is_round']);
  assert.deepEqual(MODEL.features.behavior, ['is_new_recipient', 'prior_count', 'tx_count_30m', 'value_24h_ratio', 'indirect_connection', 'is_p2m']);
  assert.deepEqual(MODEL.features.context, ['is_night', 'hour_deviation', 'new_device', 'account_age_days']);
  for (const c of ['amount', 'behavior', 'context']) {
    const comp = MODEL.components[c];
    assert.equal(comp.trees.length, 60, c + ' has 60 trees');
    assert.ok(comp.base_score > 0 && comp.base_score < 1);
    for (const tree of comp.trees) {
      for (const n of tree) {
        if ('v' in n) assert.equal(Object.keys(n).length, 1);
        else {
          assert.deepEqual(Object.keys(n).sort(), ['f', 'l', 'r', 't']);
          assert.ok(n.f >= 0 && n.f < MODEL.features[c].length);
          assert.ok(n.l < tree.length && n.r < tree.length);
        }
      }
      assert.ok(tree.length <= 15, 'depth 3 tree has at most 15 nodes');
    }
  }
  assert.deepEqual(MODEL.stacker.inputs, ['p_amount', 'p_behavior', 'p_context', 'graph', 'receiver']);
  assert.equal(MODEL.stacker.weights.length, 5);
  assert.deepEqual(MODEL.graph.hop_factor, [0, 0.2, 0.5, 0.8]);
});

test('a missing or broken model fails clearly (no fallback)', async () => {
  const broken = loadApp(null);
  assert.match(broken.getModelError(), /missing/i);
  const db = await (async () => { broken.setNow(() => T0); return broken.seedDb({ fastHash: true }); })();
  const s = broken.findUserByUpi(db, 'yogesh@yogii');
  assert.throws(() => broken.assess(db, { sender: s, recipient: broken.resolveKnown(db, 'rahul@upi'), amount: 500, at: T0 }), /missing/i);
  const wrong = JSON.parse(JSON.stringify(MODEL));
  wrong.components.amount.features = ['log_amount'];
  const other = loadApp(wrong);
  assert.match(other.getModelError(), /features/i);
});

// ------------------------------------------------------------------ scenarios
test('scenario: Yogesh pays rahul@upi 500 is LOW, then completed, balance drops once', async () => {
  const db = await freshDb();
  const before = user(db, 'yogesh@yogii').balance;
  const p = pay(db, 'yogesh@yogii', 'rahul@upi', 500);
  assert.equal(p.risk.band, 'LOW');
  assert.equal(p.status, 'COMPLETED');
  assert.equal(user(db, 'yogesh@yogii').balance, before - 500);
});

test('scenario: Yogesh pays techgadgets 24,500 is HIGH with amount and new-recipient reasons', async () => {
  const db = await freshDb();
  const p = pay(db, 'yogesh@yogii', 'techgadgets@merchant', 24500, {}, { stopAfterRisk: true });
  assert.ok(p.risk.score >= 60 && p.risk.score <= 84, 'score ' + p.risk.score);
  assert.equal(p.risk.band, 'HIGH');
  assert.equal(p.status, 'NEEDS_VERIFICATION');
  const codes = p.risk.reasons.map((r) => r.code);
  assert.ok(codes.includes('AMOUNT_ABOVE_USUAL'));
  assert.ok(codes.includes('NEW_RECIPIENT'));
  for (const r of p.risk.reasons) assert.doesNotMatch(r.text, /\d/, 'reason text exposes no thresholds');
});

test('scenario: crypto_drain@unknown is VERY_HIGH, receiver High, limit 0', async () => {
  const db = await freshDb();
  const before = user(db, 'yogesh@yogii').balance;
  const p = pay(db, 'yogesh@yogii', 'crypto_drain@unknown', 1000);
  assert.equal(p.risk.band, 'VERY_HIGH');
  assert.equal(p.risk.receiver.level, 'High');
  assert.equal(p.status, 'BLOCKED');
  assert.equal(user(db, 'yogesh@yogii').balance, before);
  const L = api.computeLimits(db, { sender: user(db, 'yogesh@yogii'), recipient: api.resolveKnown(db, 'crypto_drain@unknown'), controls: {}, at: clock });
  assert.equal(L.noChecks, 0);
  assert.equal(L.strongWarning, 0);
  assert.equal(L.maxAllowed, 0);
});

test('scenario: payment chain (2-hop HIGH not blocked, 3-hop VERY_HIGH) and indirect path', async () => {
  const db = await freshDb();
  const p1 = pay(db, 'yogesh@yogii', 'visrojit@yogii', 10000);
  assert.notEqual(p1.risk.band, 'VERY_HIGH');
  assert.equal(p1.status, 'COMPLETED');
  assert.equal(user(db, 'visrojit@yogii').balance, 310000, 'transfers between Yogii users credit the receiver');

  const p2 = pay(db, 'visrojit@yogii', 'dinesh@yogii', 9800);
  assert.equal(p2.risk.graph.hops, 2);
  assert.equal(p2.risk.band, 'HIGH');
  assert.equal(p2.status, 'COMPLETED');
  assert.ok(p2.risk.reasons.some((r) => r.code === 'POSSIBLE_PASS_THROUGH_PATTERN'));
  assert.equal(p2.risk.graph.links[0].from, 'yogesh@yogii');
  assert.equal(p2.risk.graph.links[0].level, 'High');

  const p3 = pay(db, 'dinesh@yogii', 'rahul@upi', 9500);
  assert.equal(p3.risk.graph.hops, 3);
  assert.equal(p3.risk.band, 'VERY_HIGH');
  assert.equal(p3.status, 'BLOCKED');
  assert.deepEqual(plain(p3.risk.graph.links.map((l) => l.from)), ['yogesh@yogii', 'visrojit@yogii']);

  const p4 = pay(db, 'yogesh@yogii', 'dinesh@yogii', 2000, {}, { stopAfterRisk: true });
  assert.equal(p4.risk.indirect.found, true);
  assert.deepEqual(plain(p4.risk.indirect.path), ['yogesh@yogii', 'visrojit@yogii', 'dinesh@yogii']);
  assert.ok(p4.risk.reasons.some((r) => r.code === 'INDIRECT_CONNECTION'));
  assert.equal(p4.risk.features.indirect_connection, 1);
});

// ------------------------------------------------------------------ graph
function addCompleted(db, from, to, amount, at) {
  const s = user(db, from);
  db.payments.push({ id: 'x' + (++keyN), key: 'x' + keyN, fromUserId: s ? s.id : null, from, to, amount, createdAt: at, status: 'COMPLETED', timeline: [], settled: true });
}

test('chain respects the 3-hop limit', async () => {
  const db = await freshDb();
  // four earlier links: rahul? no — use Yogii users plus extra accounts that exist only as payers
  addCompleted(db, 'a@yogii', 'b@yogii', 10000, T0 - 50 * 60000);
  addCompleted(db, 'b@yogii', 'yogesh@yogii', 9900, T0 - 40 * 60000);
  addCompleted(db, 'yogesh@yogii', 'visrojit@yogii', 9800, T0 - 30 * 60000);
  addCompleted(db, 'visrojit@yogii', 'dinesh@yogii', 9700, T0 - 20 * 60000);
  const g = api.paymentChain(db, 'dinesh@yogii', 9600, T0);
  assert.equal(g.hops, 3, 'capped at 3 hops');
  assert.equal(g.links.length, 2, 'follows at most 2 upstream payments');
  assert.ok(Math.abs(g.score - 0.8 * (0.6 + 0.4 * g.avgSimilarity)) < 1e-12);
});

test('a 2-hop chain alone does not block', async () => {
  const db = await freshDb();
  addCompleted(db, 'yogesh@yogii', 'visrojit@yogii', 1000, T0 - 20 * 60000);
  const s = user(db, 'visrojit@yogii');
  const r = api.assess(db, { sender: s, recipient: api.resolveKnown(db, 'freshmarket@merchant'), amount: 1000, at: T0 });
  assert.equal(r.graph.hops, 2);
  assert.notEqual(r.band, 'VERY_HIGH');
  assert.ok(r.score < 60, 'chain alone stays below HIGH: ' + r.score);
});

test('chain ignores payments outside 2 hours or 25% of the amount', async () => {
  const db = await freshDb();
  addCompleted(db, 'yogesh@yogii', 'visrojit@yogii', 10000, T0 - 3 * 3600000);
  addCompleted(db, 'dinesh@yogii', 'visrojit@yogii', 5000, T0 - 10 * 60000);
  assert.equal(api.paymentChain(db, 'visrojit@yogii', 9800, T0).hops, 0);
});

test('cycles do not break traversal', async () => {
  const db = await freshDb();
  addCompleted(db, 'dinesh@yogii', 'visrojit@yogii', 9900, T0 - 30 * 60000);
  addCompleted(db, 'visrojit@yogii', 'dinesh@yogii', 9950, T0 - 20 * 60000);
  addCompleted(db, 'dinesh@yogii', 'visrojit@yogii', 9900, T0 - 10 * 60000);
  const g = api.paymentChain(db, 'visrojit@yogii', 9800, T0);
  assert.ok(g.hops <= 3);
  assert.ok(new Set(g.links.map((l) => l.from)).size === g.links.length, 'no account visited twice');
  // BFS over a cycle terminates too
  addCompleted(db, 'yogesh@yogii', 'visrojit@yogii', 100, T0 - 60000);
  assert.deepEqual(plain(api.indirectPath(db, 'yogesh@yogii', 'dinesh@yogii', T0)), ['yogesh@yogii', 'visrojit@yogii', 'dinesh@yogii']);
  assert.equal(api.indirectPath(db, 'yogesh@yogii', 'nobody@upi', T0), null);
});

test('circular mean of hours wraps around midnight', () => {
  const m = api.circularMeanHour([23, 1, 0]);
  assert.ok(m < 0.01 || m > 23.99, 'mean ' + m);
  assert.ok(Math.abs(api.circularMeanHour([10, 12, 14]) - 12) < 1e-9);
});

// ------------------------------------------------------------------ balances
test('blocked, failed and rejected payments never change balances', async () => {
  const db = await freshDb();
  const y = user(db, 'yogesh@yogii');
  const before = y.balance;
  pay(db, 'yogesh@yogii', 'crypto_drain@unknown', 2000);
  const failed = pay(db, 'yogesh@yogii', 'rahul@upi', 500, { outcome: 'failure' });
  assert.equal(failed.status, 'FAILED');
  const rejected = pay(db, 'yogesh@yogii', 'techgadgets@merchant', 24500, {}, { stopAfterRisk: true });
  api.rejectPayment(rejected);
  assert.equal(rejected.status, 'FAILED');
  assert.equal(rejected.decision, 'REJECTED');
  assert.equal(y.balance, before);
});

test('completed payments change balances exactly once, even with duplicate settlement', async () => {
  const db = await freshDb();
  const y = user(db, 'yogesh@yogii'), v = user(db, 'visrojit@yogii');
  const p = pay(db, 'yogesh@yogii', 'visrojit@yogii', 1500);
  assert.equal(p.status, 'COMPLETED');
  const provider = new api.MockPaymentProvider(db);
  assert.equal(provider.settle(p), false, 'second settle is a no-op');
  provider.callback(p);
  assert.equal(y.balance, 300000 - 1500);
  assert.equal(v.balance, 300000 + 1500);
});

test('pending payment with a duplicate callback debits once', async () => {
  const db = await freshDb();
  const y = user(db, 'yogesh@yogii');
  const p = pay(db, 'yogesh@yogii', 'rahul@upi', 700, { outcome: 'pending' });
  assert.equal(p.status, 'PENDING');
  assert.equal(y.balance, 300000, 'pending does not debit yet');
  const provider = new api.MockPaymentProvider(db);
  const first = provider.callback(p);
  const second = provider.callback(p);
  assert.equal(first.changed, true);
  assert.equal(second.duplicate, true);
  assert.equal(p.status, 'COMPLETED');
  assert.equal(y.balance, 300000 - 700);
});

test('idempotency key returns the same payment', async () => {
  const db = await freshDb();
  const s = user(db, 'yogesh@yogii');
  const r = api.resolveKnown(db, 'rahul@upi');
  const a = api.createPayment(db, { senderId: s.id, recipient: r, amount: 300, key: 'same-key' });
  const b = api.createPayment(db, { senderId: s.id, recipient: r, amount: 300, key: 'same-key' });
  assert.equal(a, b);
  assert.equal(db.payments.filter((p) => p.key === 'same-key').length, 1);
});

test('amounts above the demo ceiling or the balance are refused', async () => {
  const db = await freshDb();
  const s = user(db, 'yogesh@yogii');
  const r = api.resolveKnown(db, 'rahul@upi');
  assert.throws(() => api.createPayment(db, { senderId: s.id, recipient: r, amount: 100001, key: 'c1' }), /ceiling/);
  s.balance = 50;
  assert.throws(() => api.createPayment(db, { senderId: s.id, recipient: r, amount: 60, key: 'c2' }), /balance/);
});

test('wrong demo PIN does not move money', async () => {
  const db = await freshDb();
  const s = user(db, 'yogesh@yogii');
  const p = api.createPayment(db, { senderId: s.id, recipient: api.resolveKnown(db, 'rahul@upi'), amount: 500, key: 'pin1' });
  api.assessPayment(db, p);
  api.approvePayment(p);
  assert.equal(api.authorizePayment(db, p, '0000').ok, false);
  assert.equal(s.balance, 300000);
  assert.equal(p.status, 'ASSESSING');
});

// ------------------------------------------------------------------ state machine
test('illegal transitions throw', () => {
  const mk = (status) => ({ status, timeline: [] });
  assert.throws(() => api.transition(mk('DRAFT'), 'COMPLETED'), /Illegal/);
  assert.throws(() => api.transition(mk('BLOCKED'), 'COMPLETED'), /Illegal/);
  assert.throws(() => api.transition(mk('FAILED'), 'PENDING'), /Illegal/);
  assert.throws(() => api.transition(mk('REVERSED'), 'COMPLETED'), /Illegal/);
  assert.throws(() => api.transition(mk('COMPLETED'), 'FAILED'), /Illegal/);
  assert.throws(() => api.transition(mk('PENDING'), 'BLOCKED'), /Illegal/);
  assert.throws(() => api.transition(mk('NEEDS_VERIFICATION'), 'BLOCKED'), /Illegal/);
  const p = mk('DRAFT');
  api.transition(p, 'ASSESSING'); api.transition(p, 'NEEDS_VERIFICATION'); api.transition(p, 'PENDING');
  api.transition(p, 'COMPLETED'); api.transition(p, 'REVERSED');
  assert.equal(p.status, 'REVERSED');
  for (const terminal of ['BLOCKED', 'FAILED', 'REVERSED']) assert.deepEqual(plain(api.TRANSITIONS[terminal]), []);
});

test('verification is required before authorising a MEDIUM/HIGH payment', async () => {
  const db = await freshDb();
  const p = pay(db, 'yogesh@yogii', 'techgadgets@merchant', 24500, {}, { stopAfterRisk: true });
  api.approvePayment(p);
  assert.throws(() => api.authorizePayment(db, p, '1234'), /verification/i);
});

// ------------------------------------------------------------------ limits
test('at each model limit the score is below its threshold', async () => {
  const db = await freshDb();
  const s = user(db, 'yogesh@yogii');
  const cases = [
    ['rahul@upi', {}], ['techgadgets@merchant', {}], ['visrojit@yogii', {}],
    ['techgadgets@merchant', { night: true, newDevice: true }], ['newshop@okbank', {}], ['newshop@okbank', { night: true }]
  ];
  let checked = 0;
  for (const [to, controls] of cases) {
    const r = api.resolveKnown(db, to);
    const L = api.computeLimits(db, { sender: s, recipient: r, controls, at: clock });
    const pairs = [[L.noChecks, 30], [L.verification, 60], [L.strongWarning, 85]];
    let prev = 0;
    for (const [limit, T] of pairs) {
      if (limit === null) continue;
      assert.equal(limit % 100, 0, 'rounded down to Rs 100');
      assert.ok(limit >= prev, 'limits are ordered');
      prev = limit;
      if (limit > 0) {
        const at = api.assess(db, { sender: s, recipient: r, amount: limit, controls, at: clock });
        assert.ok(at.score < T, `${to} limit ${limit}: score ${at.score} < ${T}`);
        const above = api.assess(db, { sender: s, recipient: r, amount: limit + 100, controls, at: clock });
        assert.ok(above.score >= T, `${to} limit ${limit}+100: score ${above.score} >= ${T}`);
        checked++;
      }
    }
  }
  assert.ok(checked >= 3, 'some limits were actually checked');
});

test('changing a demo control recalculates the limits', async () => {
  const db = await freshDb();
  const s = user(db, 'yogesh@yogii');
  const r = api.resolveKnown(db, 'techgadgets@merchant');
  const a = api.computeLimits(db, { sender: s, recipient: r, controls: {}, at: clock });
  const b = api.computeLimits(db, { sender: s, recipient: r, controls: { night: true, newDevice: true }, at: clock });
  assert.notDeepEqual([a.noChecks, a.verification], [b.noChecks, b.verification]);
});

test('watchlisted recipient has limit 0', async () => {
  const db = await freshDb();
  const L = api.computeLimits(db, { sender: user(db, 'yogesh@yogii'), recipient: api.resolveKnown(db, 'crypto_drain@unknown'), controls: {}, at: clock });
  assert.equal(L.noChecks, 0);
  assert.equal(L.verification, 0);
  assert.equal(L.strongWarning, 0);
  assert.equal(L.maxAllowed, 0);
});

// ------------------------------------------------------------------ receiver side
test('receiver side signals', async () => {
  const db = await freshDb();
  const unreg = api.receiverRisk(db, api.resolveKnown(db, 'someone@okbank'), 'yogesh@yogii', T0);
  assert.equal(unreg.score, 0.25);
  assert.equal(unreg.level, 'Normal');
  for (const from of ['a@x', 'b@x', 'c@x']) addCompleted(db, from, 'someone@okbank', 100, T0 - 60000);
  const busy = api.receiverRisk(db, api.resolveKnown(db, 'someone@okbank'), 'yogesh@yogii', T0);
  assert.equal(busy.score, 0.5);
  assert.equal(busy.level, 'Elevated');
  const watch = api.receiverRisk(db, api.resolveKnown(db, 'crypto_drain@unknown'), 'yogesh@yogii', T0);
  assert.equal(watch.score, 1);
  assert.equal(watch.level, 'High');
  assert.ok(!/balance|history/i.test(watch.note), 'note stays generic');
});

// ------------------------------------------------------------------ accounts
test('registration rules and PBKDF2 sign-in with lockout', async () => {
  const db = await freshDb();
  const bad = api.validateRegistration({ name: 'A', email: 'nope', phone: '12345', password: 'short' }, db);
  assert.deepEqual(Object.keys(bad).sort(), ['email', 'name', 'password', 'phone']);
  const res = await api.registerUser(db, { name: 'Test Person', email: 'test@example.com', phone: '9123456789', password: 'Abcdefghij1' }, { iterations: 1000 });
  assert.ok(res.ok);
  assert.equal(res.user.balance, 300000);
  assert.ok(!('password' in res.user));
  assert.match(res.user.hash, /^[0-9a-f]{64}$/);
  assert.match(res.user.salt, /^[0-9a-f]{32}$/);
  const ok = await api.signIn(db, 'TEST@example.com', 'Abcdefghij1');
  assert.ok(ok.ok);
  assert.equal(api.currentUser(db).id, res.user.id);
  clock += 13 * 3600000;
  assert.equal(api.currentUser(db), null, '12-hour session expires');
  for (let i = 0; i < 4; i++) {
    const r = await api.signIn(db, 'test@example.com', 'wrong');
    assert.equal(r.error, 'Email or password is incorrect.');
  }
  const fifth = await api.signIn(db, 'test@example.com', 'wrong');
  assert.ok(fifth.locked);
  const during = await api.signIn(db, 'test@example.com', 'Abcdefghij1');
  assert.equal(during.ok, false, 'locked even with the right password');
  clock += 61000;
  const after = await api.signIn(db, 'test@example.com', 'Abcdefghij1');
  assert.ok(after.ok);
  const unknown = await api.signIn(db, 'ghost@example.com', 'x');
  assert.equal(unknown.error, 'Email or password is incorrect.', 'generic error for unknown email');
});

test('recipient resolution by UPI ID and phone', async () => {
  const db = await freshDb();
  const y = user(db, 'yogesh@yogii');
  assert.equal(api.resolveRecipient(db, '9876543211', y.id).recipient.upi, 'visrojit@yogii');
  assert.equal(api.resolveRecipient(db, 'TechGadgets@merchant', y.id).recipient.type, 'merchant');
  assert.equal(api.resolveRecipient(db, 'new.person@okbank', y.id).recipient.registered, false);
  assert.match(api.resolveRecipient(db, 'yogesh@yogii', y.id).error, /yourself/);
  assert.match(api.resolveRecipient(db, '9000000000', y.id).error, /No Yogii account/);
  assert.match(api.resolveRecipient(db, 'not an id', y.id).error, /UPI ID/);
});
