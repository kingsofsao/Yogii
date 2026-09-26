/*
 * Yogii Risk Web: simulated UPI-style payments with a prototype fraud-risk engine.
 *
 * EVERYTHING IS SIMULATED. No real UPI, bank or NPCI connection exists. Balances
 * are demo numbers. The risk model was trained on synthetic data only and its
 * thresholds are Yogii prototype values, not RBI, NPCI or bank standards.
 *
 * Layout of this file:
 *   1. Constants, clock, storage
 *   2. Model loading and validation
 *   3. Demo directory and seed data
 *   4. Risk engine (features, XGBoost trees, payment graph, receiver side, stacker, reasons)
 *   5. Model-based limits
 *   6. Payment state machine, MockPaymentProvider, payment service
 *   7. Accounts (PBKDF2), sessions, lockout
 *   8. UI
 *
 * Tests load this file with globalThis.__YOGII_TEST__ = { model } set; the UI then
 * does not boot and the internals are exposed on __YOGII_TEST__.api.
 */
(function (root) {
  'use strict';

  var TEST = root.__YOGII_TEST__ || null;

  // ------------------------------------------------------------------
  // 1. Constants, clock, storage
  // ------------------------------------------------------------------
  var MIN = 60 * 1000;
  var HOUR = 60 * MIN;
  var DAY = 24 * HOUR;
  var DEMO_PIN = '1234'; // compared in memory only, never stored; not a UPI PIN
  var DEMO_CEILING = 100000;
  var START_BALANCE = 300000;
  var SESSION_MS = 12 * HOUR;
  var LOCK_MS = 60 * 1000;
  var MAX_FAILS = 5;
  var PBKDF2_ITERATIONS = 150000;
  var STORAGE_KEY = 'yogii-risk-web.v1';
  var DATA_VERSION = 1;

  var FEATURES = {
    amount: ['log_amount', 'amount_ratio', 'amount_z', 'share_of_balance', 'is_round'],
    behavior: ['is_new_recipient', 'prior_count', 'tx_count_30m', 'value_24h_ratio', 'indirect_connection', 'is_p2m'],
    context: ['is_night', 'hour_deviation', 'new_device', 'account_age_days']
  };
  var BAND_ORDER = ['LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'];

  var nowFn = function () { return Date.now(); };
  function now() { return nowFn(); }

  var Storage = {
    get: function (key) {
      try {
        var raw = root.localStorage ? root.localStorage.getItem(key) : null;
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    },
    set: function (key, value) {
      try { if (root.localStorage) root.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
    },
    remove: function (key) {
      try { if (root.localStorage) root.localStorage.removeItem(key); } catch (e) { /* ignore */ }
    }
  };

  // ------------------------------------------------------------------
  // 2. Model loading and validation (no fallback: a missing model is an error)
  // ------------------------------------------------------------------
  function validateModel(m) {
    if (!m || typeof m !== 'object') throw new Error('Risk model file is missing or empty.');
    if (m.format !== 'yogii-risk-model') throw new Error('Risk model has an unknown format.');
    ['amount', 'behavior', 'context'].forEach(function (c) {
      var comp = m.components && m.components[c];
      if (!comp || !Array.isArray(comp.trees) || comp.trees.length === 0) throw new Error('Risk model is missing the ' + c + ' component.');
      if (JSON.stringify(comp.features) !== JSON.stringify(FEATURES[c]) || JSON.stringify(m.features[c]) !== JSON.stringify(FEATURES[c])) {
        throw new Error('Risk model features for ' + c + ' do not match this app.');
      }
      if (!(comp.base_score > 0 && comp.base_score < 1)) throw new Error('Risk model ' + c + ' has an invalid base score.');
    });
    if (!m.stacker || !Array.isArray(m.stacker.weights) || m.stacker.weights.length !== 5) throw new Error('Risk model stacker is invalid.');
    if (!m.graph || !m.receiver || !Array.isArray(m.bands)) throw new Error('Risk model settings are incomplete.');
    return m;
  }

  var MODEL = null;
  var MODEL_ERROR = null;
  function setModel(m) {
    try { MODEL = validateModel(m); MODEL_ERROR = null; } catch (e) { MODEL = null; MODEL_ERROR = e.message; }
    return MODEL;
  }
  function requireModel() {
    if (!MODEL) throw new Error(MODEL_ERROR || 'Risk model is not loaded.');
    return MODEL;
  }

  // ------------------------------------------------------------------
  // 3. Demo directory and seed data (all fictional)
  // ------------------------------------------------------------------
  var SEED_USERS = [
    { id: 'u_yogesh', name: 'Yogesh Kumar', email: 'yogesh@demo.yogii', upi: 'yogesh@yogii', phone: '9876543210', ageDays: 400 },
    { id: 'u_visrojit', name: 'Visrojit Sharma', email: 'visrojit@demo.yogii', upi: 'visrojit@yogii', phone: '9876543211', ageDays: 250 },
    { id: 'u_dinesh', name: 'Dinesh Patel', email: 'dinesh@demo.yogii', upi: 'dinesh@yogii', phone: '9876543212', ageDays: 180 }
  ];
  var SEED_PASSWORD = 'Password123!';

  // Recipients that are not Yogii users. "registered" means known to the demo directory.
  var DIRECTORY = [
    { upi: 'rahul@upi', name: 'Rahul Mehta', type: 'contact', registered: true, ageDays: 900 },
    { upi: 'freshmarket@merchant', name: 'Fresh Market', type: 'merchant', registered: true, ageDays: 1200 },
    { upi: 'campuscafe@merchant', name: 'Campus Cafe', type: 'merchant', registered: true, ageDays: 800 },
    { upi: 'techgadgets@merchant', name: 'Tech Gadgets', type: 'merchant', registered: true, ageDays: 600 },
    { upi: 'crypto_drain@unknown', name: 'crypto_drain', type: 'unknown', registered: false, ageDays: 2, watchlist: true }
  ];

  // [from, to, amount, daysAgo, hourOfDay] — times are relative to "now" when seeding.
  var SEED_PAYMENTS = [
    ['yogesh@yogii', 'rahul@upi', 800, 2, 11], ['yogesh@yogii', 'rahul@upi', 1200, 5, 19],
    ['yogesh@yogii', 'rahul@upi', 1500, 9, 13], ['yogesh@yogii', 'rahul@upi', 900, 14, 18],
    ['yogesh@yogii', 'rahul@upi', 2000, 20, 12], ['yogesh@yogii', 'rahul@upi', 1100, 26, 16],
    ['yogesh@yogii', 'freshmarket@merchant', 1450, 3, 17], ['yogesh@yogii', 'freshmarket@merchant', 2300, 8, 10],
    ['yogesh@yogii', 'freshmarket@merchant', 1750, 16, 18], ['yogesh@yogii', 'freshmarket@merchant', 1600, 23, 11],
    ['yogesh@yogii', 'campuscafe@merchant', 250, 4, 13], ['yogesh@yogii', 'campuscafe@merchant', 400, 12, 14],
    ['yogesh@yogii', 'campuscafe@merchant', 320, 18, 15],
    ['visrojit@yogii', 'freshmarket@merchant', 3200, 3, 12], ['visrojit@yogii', 'freshmarket@merchant', 2600, 10, 18],
    ['visrojit@yogii', 'campuscafe@merchant', 900, 6, 15], ['visrojit@yogii', 'techgadgets@merchant', 4500, 15, 16],
    ['visrojit@yogii', 'freshmarket@merchant', 2800, 21, 11], ['visrojit@yogii', 'campuscafe@merchant', 1600, 25, 14],
    ['dinesh@yogii', 'freshmarket@merchant', 1500, 2, 10], ['dinesh@yogii', 'campuscafe@merchant', 600, 5, 13],
    ['dinesh@yogii', 'freshmarket@merchant', 2100, 11, 17], ['dinesh@yogii', 'techgadgets@merchant', 2800, 17, 15],
    ['dinesh@yogii', 'campuscafe@merchant', 500, 22, 12], ['dinesh@yogii', 'freshmarket@merchant', 1500, 27, 19]
  ];

  function startOfLocalDay(t) { var d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); }

  function emptyDb() {
    return { version: DATA_VERSION, users: [], payments: [], session: null, lockouts: {}, prefs: { theme: 'system', hideBalance: false }, seq: 0 };
  }

  function seedPayments(db, t) {
    var day0 = startOfLocalDay(t);
    SEED_PAYMENTS.forEach(function (s, i) {
      var sender = findUserByUpi(db, s[0]);
      var r = resolveKnown(db, s[1]);
      var at = day0 - s[3] * DAY + s[4] * HOUR;
      db.payments.push({
        id: 'seed' + String(i + 1).padStart(3, '0'), key: 'seed-' + (i + 1), fromUserId: sender.id, from: s[0],
        fromName: sender.name, to: s[1], toName: r.name, toType: r.type, amount: s[2], createdAt: at, updatedAt: at,
        status: 'COMPLETED', settled: true, seeded: true, timeline: [{ status: 'COMPLETED', at: at, note: 'Demo history (fictional)' }],
        risk: null, controls: null, seq: ++db.seq
      });
    });
  }

  async function seedDb(options) {
    var t = now();
    var db = emptyDb();
    var fast = options && options.fastHash;
    for (var i = 0; i < SEED_USERS.length; i++) {
      var u = SEED_USERS[i];
      var cred = await hashPassword(SEED_PASSWORD, null, fast ? 1000 : PBKDF2_ITERATIONS);
      db.users.push({ id: u.id, name: u.name, email: u.email, upi: u.upi, phone: u.phone, balance: START_BALANCE,
        createdAt: t - u.ageDays * DAY, salt: cred.salt, hash: cred.hash, iterations: cred.iterations, seeded: true, lastSignIn: null });
    }
    seedPayments(db, t);
    return db;
  }

  // ------------------------------------------------------------------
  // Lookups
  // ------------------------------------------------------------------
  function findUser(db, id) { for (var i = 0; i < db.users.length; i++) if (db.users[i].id === id) return db.users[i]; return null; }
  function findUserByUpi(db, upi) { for (var i = 0; i < db.users.length; i++) if (db.users[i].upi === upi) return db.users[i]; return null; }
  function findUserByEmail(db, email) {
    var e = String(email || '').trim().toLowerCase();
    for (var i = 0; i < db.users.length; i++) if (db.users[i].email === e) return db.users[i];
    return null;
  }
  function findUserByPhone(db, phone) { for (var i = 0; i < db.users.length; i++) if (db.users[i].phone === phone) return db.users[i]; return null; }
  function directoryEntry(upi) { for (var i = 0; i < DIRECTORY.length; i++) if (DIRECTORY[i].upi === upi) return DIRECTORY[i]; return null; }
  function findPayment(db, id) { for (var i = 0; i < db.payments.length; i++) if (db.payments[i].id === id) return db.payments[i]; return null; }

  var UPI_RE = /^[a-z0-9][a-z0-9._-]{1,63}@[a-z][a-z0-9.-]{1,31}$/;

  function resolveKnown(db, upi) {
    var u = findUserByUpi(db, upi);
    if (u) return { upi: u.upi, name: u.name, type: 'user', registered: true, userId: u.id, createdAt: u.createdAt, watchlist: false };
    var d = directoryEntry(upi);
    if (d) return { upi: d.upi, name: d.name, type: d.type, registered: d.registered, createdAt: now() - d.ageDays * DAY, watchlist: !!d.watchlist };
    return { upi: upi, name: 'Unregistered UPI ID', type: 'unregistered', registered: false, createdAt: null, watchlist: false };
  }

  /** Resolve what the sender typed (UPI ID or 10-digit mobile) into a recipient. */
  function resolveRecipient(db, input, senderId) {
    var raw = String(input || '').trim().toLowerCase().replace(/\s+/g, '');
    if (!raw) return { error: 'Enter a UPI ID or a 10-digit mobile number.' };
    var r;
    if (/^(\+91)?[0-9]{10}$/.test(raw)) {
      var phone = raw.slice(-10);
      var u = findUserByPhone(db, phone);
      if (!u) return { error: 'No Yogii account uses this mobile number.' };
      r = resolveKnown(db, u.upi);
    } else if (UPI_RE.test(raw)) {
      r = resolveKnown(db, raw);
    } else {
      return { error: 'That doesn’t look like a UPI ID (name@bank) or a 10-digit mobile number.' };
    }
    if (r.userId && r.userId === senderId) return { error: 'You can’t send money to yourself.' };
    return { recipient: r };
  }

  // ------------------------------------------------------------------
  // 4. Risk engine
  // ------------------------------------------------------------------
  function clip(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
  function sigmoid(x) { return 1 / (1 + Math.exp(-x)); }

  function isOutflow(p) { return p.status === 'COMPLETED' || p.status === 'PENDING'; }

  function localHour(t) { var d = new Date(t); return d.getHours() + d.getMinutes() / 60; }

  /** Circular mean of hours of day (so 23:00 and 01:00 average to midnight, not noon). */
  function circularMeanHour(hours) {
    var s = 0, c = 0;
    hours.forEach(function (h) { var a = h / 24 * 2 * Math.PI; s += Math.sin(a); c += Math.cos(a); });
    var ang = Math.atan2(s, c);
    if (ang < 0) ang += 2 * Math.PI;
    return ang / (2 * Math.PI) * 24;
  }
  function circularDistance(a, b) { var d = Math.abs(a - b) % 24; return Math.min(d, 24 - d); }

  function senderHistory(db, sender, at, excludeId) {
    return db.payments.filter(function (p) {
      return p.fromUserId === sender.id && p.id !== excludeId && isOutflow(p) && p.createdAt <= at;
    });
  }

  function buildFeatures(db, ctx) {
    var sender = ctx.sender, r = ctx.recipient, amount = ctx.amount, at = ctx.at, controls = ctx.controls || {};
    var hist = senderHistory(db, sender, at, ctx.excludeId);
    var last30 = hist.filter(function (p) { return at - p.createdAt <= 30 * DAY; });
    var avg = 2000, std = 1000;
    if (last30.length >= 3) {
      avg = last30.reduce(function (s, p) { return s + p.amount; }, 0) / last30.length;
      std = Math.sqrt(last30.reduce(function (s, p) { return s + (p.amount - avg) * (p.amount - avg); }, 0) / last30.length);
    }
    var prior = hist.filter(function (p) { return p.to === r.upi; }).length;
    var isNew = prior === 0 ? 1 : 0;
    var c30 = hist.filter(function (p) { return at - p.createdAt <= 30 * MIN; }).length;
    var v24 = hist.filter(function (p) { return at - p.createdAt <= DAY; }).reduce(function (s, p) { return s + p.amount; }, 0);
    var path = isNew ? indirectPath(db, sender.upi, r.upi, at, ctx.excludeId) : null;
    var hour = controls.night ? 2 : localHour(at);
    var hours = hist.filter(function (p) { return at - p.createdAt <= 90 * DAY; }).map(function (p) { return localHour(p.createdAt); });
    var dev = hours.length >= 3 ? circularDistance(hour, circularMeanHour(hours)) : 0;
    var f = {
      log_amount: Math.log(1 + amount),
      amount_ratio: amount / avg,
      amount_z: (amount - avg) / Math.max(std, 0.25 * avg, 100),
      share_of_balance: clip(amount / Math.max(sender.balance, 1), 0, 5),
      is_round: amount >= 5000 && amount % 1000 === 0 ? 1 : 0,
      is_new_recipient: isNew,
      prior_count: Math.min(prior, 50),
      tx_count_30m: c30,
      value_24h_ratio: v24 / Math.max(avg, 100),
      indirect_connection: path ? 1 : 0,
      is_p2m: r.type === 'merchant' ? 1 : 0,
      is_night: hour < 5 ? 1 : 0,
      hour_deviation: dev,
      new_device: controls.newDevice ? 1 : 0,
      account_age_days: Math.min(3650, Math.max(0, Math.floor((at - sender.createdAt) / DAY)))
    };
    return { features: f, indirectPath: path };
  }

  function predictComponent(comp, x) {
    var b = comp.base_score;
    var margin = Math.log(b / (1 - b));
    for (var i = 0; i < comp.trees.length; i++) {
      var nodes = comp.trees[i], k = 0;
      while (nodes[k].v === undefined) {
        var nd = nodes[k];
        k = Math.fround(x[nd.f]) < nd.t ? nd.l : nd.r; // x < t goes left (float32 compare, like xgboost)
      }
      margin += nodes[k].v;
    }
    return sigmoid(margin);
  }

  function componentProbabilities(f) {
    var m = requireModel();
    var out = {};
    ['amount', 'behavior', 'context'].forEach(function (c) {
      out[c] = predictComponent(m.components[c], m.features[c].map(function (n) { return f[n]; }));
    });
    return out;
  }

  /** Payment chain: inbound payments within 2 h and 25% of the amount, followed upstream (cycle-safe). */
  function paymentChain(db, senderUpi, amount, at, excludeId) {
    var g = requireModel().graph;
    var windowMs = g.window_minutes * MIN;
    var links = [];
    var visited = {}; visited[senderUpi] = true;
    var node = senderUpi, outAmt = amount, outAt = at;
    while (links.length < g.max_hops - 1) {
      var best = null, bestSim = -1;
      for (var i = 0; i < db.payments.length; i++) {
        var p = db.payments[i];
        if (p.status !== 'COMPLETED' || p.to !== node || p.id === excludeId || visited[p.from]) continue;
        if (p.createdAt > outAt || outAt - p.createdAt > windowMs) continue;
        if (Math.abs(p.amount - outAmt) > g.amount_tolerance * outAmt) continue;
        var sim = 1 - Math.abs(p.amount - outAmt) / Math.max(p.amount, outAmt);
        if (sim > bestSim || (sim === bestSim && p.createdAt > best.createdAt)) { best = p; bestSim = sim; }
      }
      if (!best) break;
      var gapMin = (outAt - best.createdAt) / MIN;
      links.push({ paymentId: best.id, from: best.from, to: node, amount: best.amount, at: best.createdAt,
        similarity: bestSim, gapMinutes: gapMin, level: bestSim >= 0.9 && gapMin <= 30 ? 'High' : 'Medium' });
      visited[best.from] = true;
      node = best.from; outAmt = best.amount; outAt = best.createdAt;
    }
    // hops = payments in the chain, including this one (a lone payment is not a chain)
    var hops = links.length ? Math.min(g.max_hops, links.length + 1) : 0;
    var avgSim = links.length ? links.reduce(function (s, l) { return s + l.similarity; }, 0) / links.length : 0;
    var score = g.hop_factor[hops] * (0.6 + 0.4 * avgSim);
    return { hops: hops, links: links.reverse(), avgSimilarity: avgSim, score: hops ? score : 0 };
  }

  /** Indirect connection: BFS sender -> recipient over the last 90 days of completed payments. */
  function indirectPath(db, fromUpi, toUpi, at, excludeId) {
    var g = requireModel().graph;
    var adj = {};
    db.payments.forEach(function (p) {
      if (p.status !== 'COMPLETED' || p.id === excludeId || p.createdAt > at || at - p.createdAt > g.indirect_days * DAY) return;
      (adj[p.from] = adj[p.from] || {})[p.to] = true;
    });
    var parent = {}; parent[fromUpi] = null;
    var frontier = [fromUpi];
    for (var depth = 1; depth <= g.max_hops && frontier.length; depth++) {
      var next = [];
      for (var i = 0; i < frontier.length; i++) {
        var outs = Object.keys(adj[frontier[i]] || {}).sort();
        for (var j = 0; j < outs.length; j++) {
          var n = outs[j];
          if (n in parent) continue;
          parent[n] = frontier[i];
          if (n === toUpi) {
            if (depth < 2) return null;
            var path = [n];
            while (parent[path[0]] !== null) path.unshift(parent[path[0]]);
            return path;
          }
          next.push(n);
        }
      }
      frontier = next;
    }
    return null;
  }

  function receiverRisk(db, r, senderUpi, at) {
    var cfg = requireModel().receiver;
    var score = 0, signals = [];
    if (r.watchlist) { score = cfg.watchlist; signals.push('watchlist'); }
    else {
      if (!r.registered) { score += cfg.unregistered; signals.push('unregistered'); }
      if (r.registered && r.createdAt !== null && at - r.createdAt < cfg.new_account_days * DAY) { score += cfg.new_account; signals.push('new_account'); }
      var payers = {}, inflow = 0, outflow = 0;
      db.payments.forEach(function (p) {
        if (p.status !== 'COMPLETED' || p.createdAt > at || at - p.createdAt > DAY) return;
        if (p.to === r.upi) { inflow += p.amount; if (p.from !== senderUpi) payers[p.from] = true; }
        if (p.from === r.upi) outflow += p.amount;
      });
      if (Object.keys(payers).length >= cfg.many_payers_count) { score += cfg.many_payers; signals.push('many_payers'); }
      if (r.type === 'user' && inflow > 0 && outflow >= cfg.pass_through_ratio * inflow) { score += cfg.pass_through; signals.push('pass_through'); }
    }
    score = Math.min(1, score);
    var level = score < cfg.levels.elevated ? 'Normal' : score < cfg.levels.high ? 'Elevated' : 'High';
    var note = level === 'Normal' ? 'No unusual signals on the receiving account.'
      : level === 'Elevated' ? 'Some signals on the receiving account call for care.'
        : 'The receiving account shows strong risk signals.';
    return { score: score, level: level, note: note, signals: signals };
  }

  function bandFor(score) {
    if (score >= 85) return 'VERY_HIGH';
    if (score >= 60) return 'HIGH';
    if (score >= 30) return 'MEDIUM';
    return 'LOW';
  }

  var REASON_TEXT = {
    AMOUNT_ABOVE_USUAL: 'This amount is much higher than what you usually send.',
    NEW_RECIPIENT: 'You haven’t paid this recipient before.',
    INDIRECT_CONNECTION: 'You’re connected to this recipient only indirectly, through accounts you have paid.',
    HIGH_RECENT_VELOCITY: 'You’ve sent several payments or a lot of money in a short time.',
    UNUSUAL_TIME: 'This is an unusual time of day for you to pay.',
    DEVICE_OR_LOCATION_CHANGE: 'This payment comes from a new device or location.',
    NEW_ACCOUNT: 'Your account is new, so there is little history to compare with.',
    POSSIBLE_PASS_THROUGH_PATTERN: 'Money you received recently seems to be moving on in a similar amount (a possible pass-through).',
    RECEIVER_SIDE_RISK: 'The receiving account shows risk signals.'
  };

  function reasonsFor(f, p, graph, receiver) {
    var out = [];
    function add(code, strength) { out.push({ code: code, text: REASON_TEXT[code], strength: strength }); }
    if (f.amount_ratio >= 2.5 || f.share_of_balance >= 0.3) add('AMOUNT_ABOVE_USUAL', p.amount);
    if (f.is_new_recipient) add('NEW_RECIPIENT', p.behavior);
    if (f.indirect_connection) add('INDIRECT_CONNECTION', p.behavior * 0.9);
    if (f.tx_count_30m >= 2 || f.value_24h_ratio >= 3) add('HIGH_RECENT_VELOCITY', p.behavior * 0.95);
    if (f.is_night || f.hour_deviation >= 4) add('UNUSUAL_TIME', p.context);
    if (f.new_device) add('DEVICE_OR_LOCATION_CHANGE', p.context * 0.95);
    if (f.account_age_days < 30) add('NEW_ACCOUNT', p.context * 0.9);
    if (graph.hops >= 2) add('POSSIBLE_PASS_THROUGH_PATTERN', graph.score + 0.5);
    if (receiver.score >= 0.3) add('RECEIVER_SIDE_RISK', receiver.score + 0.5);
    out.sort(function (a, b) { return b.strength - a.strength; });
    return out.map(function (r) { return { code: r.code, text: r.text }; });
  }

  /**
   * Assess a payment. ctx: { sender, recipient, amount, at, controls, excludeId }.
   * Throws if the model is missing: there is no rule-based fallback.
   */
  function assess(db, ctx) {
    var m = requireModel();
    var at = ctx.at === undefined ? now() : ctx.at;
    var c = { sender: ctx.sender, recipient: ctx.recipient, amount: ctx.amount, at: at, controls: ctx.controls || {}, excludeId: ctx.excludeId };
    var built = buildFeatures(db, c);
    var f = built.features;
    var p = componentProbabilities(f);
    var graph = paymentChain(db, ctx.sender.upi, ctx.amount, at, ctx.excludeId);
    var receiver = receiverRisk(db, ctx.recipient, ctx.sender.upi, at);
    var x = [p.amount, p.behavior, p.context, graph.score, receiver.score];
    var raw = m.stacker.intercept;
    for (var i = 0; i < 5; i++) raw += m.stacker.weights[i] * x[i];
    var score = Math.round(clip(raw, 0, 1) * 100);
    return {
      score: score,
      band: bandFor(score),
      components: p,
      graph: graph,
      indirect: { found: !!built.indirectPath, path: built.indirectPath || [] },
      receiver: receiver,
      reasons: reasonsFor(f, p, graph, receiver),
      features: f,
      model: { version: m.version, engine: m.engine, synthetic: true },
      assessedAt: at
    };
  }

  // ------------------------------------------------------------------
  // 5. Model-based limits
  // ------------------------------------------------------------------
  var LIMIT_THRESHOLDS = [30, 60, 85];

  /**
   * Probe the engine with increasing amounts (geometric grid, then binary search on a
   * ₹100 grid) and find, for each threshold, the largest ₹100 multiple that still
   * scores below it. null means the threshold is not reached below the demo ceiling.
   */
  function computeLimits(db, ctx) {
    var cache = {};
    function scoreAt(units) {
      if (!(units in cache)) cache[units] = assess(db, { sender: ctx.sender, recipient: ctx.recipient, amount: units * 100, at: ctx.at, controls: ctx.controls }).score;
      return cache[units];
    }
    var top = DEMO_CEILING / 100;
    var grid = [];
    for (var u = 1; u < top; u = Math.max(u + 1, Math.ceil(u * 1.35))) grid.push(u);
    grid.push(top);
    var limits = {};
    LIMIT_THRESHOLDS.forEach(function (T) {
      var k = -1;
      for (var i = 0; i < grid.length; i++) { if (scoreAt(grid[i]) >= T) { k = i; break; } }
      if (k === -1) { limits[T] = null; return; }
      if (k === 0) { limits[T] = 0; return; }
      var lo = grid[k - 1], hi = grid[k]; // score(lo) < T <= score(hi)
      while (hi - lo > 1) {
        var mid = Math.floor((lo + hi) / 2);
        if (scoreAt(mid) >= T) hi = mid; else lo = mid;
      }
      limits[T] = lo * 100;
    });
    if (ctx.recipient.watchlist) { limits[30] = 0; limits[60] = 0; limits[85] = 0; } // demo watchlist policy
    var balance = Math.floor(ctx.sender.balance);
    var blockAt = limits[85] === null ? Infinity : limits[85];
    return {
      noChecks: limits[30], verification: limits[60], strongWarning: limits[85],
      ceiling: DEMO_CEILING, balance: balance,
      maxAllowed: Math.max(0, Math.min(DEMO_CEILING, balance, blockAt)),
      probes: Object.keys(cache).length
    };
  }

  // ------------------------------------------------------------------
  // 6. Payments: state machine, provider, service
  // ------------------------------------------------------------------
  var TRANSITIONS = {
    DRAFT: ['ASSESSING'],
    ASSESSING: ['NEEDS_VERIFICATION', 'BLOCKED', 'PENDING', 'COMPLETED', 'FAILED'],
    NEEDS_VERIFICATION: ['PENDING', 'COMPLETED', 'FAILED'],
    PENDING: ['COMPLETED', 'FAILED'],
    COMPLETED: ['REVERSED'],
    BLOCKED: [], FAILED: [], REVERSED: []
  };

  function canTransition(from, to) { return !!TRANSITIONS[from] && TRANSITIONS[from].indexOf(to) !== -1; }

  function transition(p, to, note) {
    if (!canTransition(p.status, to)) throw new Error('Illegal payment transition ' + p.status + ' → ' + to);
    p.status = to;
    p.updatedAt = now();
    p.timeline.push({ status: to, at: p.updatedAt, note: note || '' });
    return p;
  }

  function simpleHash(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(16).toUpperCase().padStart(8, '0');
  }

  /**
   * Simulated bank. Outcomes are deterministic: they come from the demo control the
   * user chose (success, failure or pending). Settlement is idempotent.
   */
  function MockPaymentProvider(db) { this.db = db; this.callbacks = 0; }

  MockPaymentProvider.prototype.settle = function (p) {
    if (p.settled) return false; // idempotent: never debit twice
    var sender = findUser(this.db, p.fromUserId);
    sender.balance = Math.round((sender.balance - p.amount) * 100) / 100;
    var receiver = findUserByUpi(this.db, p.to);
    if (receiver) receiver.balance = Math.round((receiver.balance + p.amount) * 100) / 100;
    p.settled = true;
    return true;
  };

  MockPaymentProvider.prototype.submit = function (p) {
    var outcome = (p.controls && p.controls.outcome) || 'success';
    p.bankRef = 'SIM' + simpleHash(p.id + ':' + p.key);
    var sender = findUser(this.db, p.fromUserId);
    if (outcome === 'failure') { p.failureReason = 'The demo bank declined this payment (simulated failure).'; transition(p, 'FAILED', 'Demo bank: declined'); return p; }
    if (sender.balance < p.amount) { p.failureReason = 'Not enough simulated balance.'; transition(p, 'FAILED', 'Demo bank: insufficient balance'); return p; }
    if (outcome === 'pending') { transition(p, 'PENDING', 'Demo bank: awaiting confirmation'); return p; }
    this.settle(p);
    transition(p, 'COMPLETED', 'Demo bank: success');
    return p;
  };

  /** Demo bank callback ("Check status"). A duplicate callback is a no-op. */
  MockPaymentProvider.prototype.callback = function (p) {
    this.callbacks++;
    if (p.status !== 'PENDING') return { changed: false, duplicate: true, status: p.status };
    var sender = findUser(this.db, p.fromUserId);
    if (sender.balance < p.amount) { p.failureReason = 'Not enough simulated balance.'; transition(p, 'FAILED', 'Demo bank callback: insufficient balance'); return { changed: true, status: p.status }; }
    this.settle(p);
    transition(p, 'COMPLETED', 'Demo bank callback: success');
    return { changed: true, duplicate: false, status: p.status };
  };

  MockPaymentProvider.prototype.reverse = function (p) {
    transition(p, 'REVERSED', 'Demo reversal');
    if (p.settled && !p.reversed) {
      var sender = findUser(this.db, p.fromUserId);
      sender.balance += p.amount;
      var receiver = findUserByUpi(this.db, p.to);
      if (receiver) receiver.balance -= p.amount;
      p.reversed = true;
    }
    return p;
  };

  function newId(db) { db.seq += 1; return 'pay' + String(db.seq).padStart(5, '0') + simpleHash(String(now()) + db.seq).slice(0, 4); }

  /** Create a payment. The same idempotency key always returns the same payment. */
  function createPayment(db, req) {
    if (req.key) {
      for (var i = 0; i < db.payments.length; i++) if (db.payments[i].key === req.key) return db.payments[i];
    }
    var sender = findUser(db, req.senderId);
    if (!sender) throw new Error('Unknown sender.');
    var amount = Number(req.amount);
    if (!(amount > 0) || Math.round(amount * 100) !== amount * 100) throw new Error('Enter a valid amount.');
    if (amount > DEMO_CEILING) throw new Error('Above the demo ceiling.');
    if (amount > sender.balance) throw new Error('Not enough simulated balance.');
    var r = req.recipient;
    var t = now();
    var p = {
      id: newId(db), key: req.key || ('auto-' + db.seq), fromUserId: sender.id, from: sender.upi, fromName: sender.name,
      to: r.upi, toName: r.name, toType: r.type, amount: amount, note: String(req.note || '').slice(0, 80),
      createdAt: t, updatedAt: t, status: 'DRAFT', timeline: [{ status: 'DRAFT', at: t, note: 'Payment created' }],
      risk: null, controls: { newDevice: !!(req.controls && req.controls.newDevice), night: !!(req.controls && req.controls.night),
        outcome: (req.controls && req.controls.outcome) || 'success' },
      settled: false, verification: null, decision: null, seq: db.seq
    };
    db.payments.push(p);
    return p;
  }

  function assessPayment(db, p) {
    transition(p, 'ASSESSING', 'Risk check started');
    var sender = findUser(db, p.fromUserId);
    var r = resolveKnown(db, p.to);
    p.risk = assess(db, { sender: sender, recipient: r, amount: p.amount, at: p.createdAt, controls: p.controls, excludeId: p.id });
    if (p.risk.band === 'VERY_HIGH') { p.failureReason = 'Blocked by the risk check.'; transition(p, 'BLOCKED', 'Risk ' + p.risk.score + ' (VERY_HIGH): blocked'); }
    else if (p.risk.band === 'MEDIUM' || p.risk.band === 'HIGH') transition(p, 'NEEDS_VERIFICATION', 'Risk ' + p.risk.score + ' (' + p.risk.band + '): demo verification needed');
    else p.timeline.push({ status: 'ASSESSING', at: now(), note: 'Risk ' + p.risk.score + ' (LOW)' });
    return p;
  }

  function rejectPayment(p, why) {
    if (p.status === 'BLOCKED' || p.status === 'FAILED') return p;
    p.decision = 'REJECTED';
    p.failureReason = why || 'You rejected this payment.';
    transition(p, 'FAILED', why || 'Rejected by you');
    return p;
  }

  function approvePayment(p) {
    if (p.status !== 'ASSESSING' && p.status !== 'NEEDS_VERIFICATION') throw new Error('This payment can’t be approved now.');
    p.decision = 'OK';
    p.timeline.push({ status: p.status, at: now(), note: 'You chose OK' });
    return p;
  }

  function verifyPayment(p) {
    if (p.status !== 'NEEDS_VERIFICATION') throw new Error('No verification needed.');
    p.verification = { at: now() };
    p.timeline.push({ status: p.status, at: now(), note: 'Demo verification passed' });
    return p;
  }

  /** Authorise with the demo PIN (compared in memory, never stored) and submit to the demo bank. */
  function authorizePayment(db, p, pin) {
    if (p.decision !== 'OK') throw new Error('Choose OK first.');
    if (p.status === 'NEEDS_VERIFICATION' && !p.verification) throw new Error('Demo verification is needed first.');
    if (p.status !== 'ASSESSING' && p.status !== 'NEEDS_VERIFICATION') throw new Error('This payment can’t be authorised now.');
    if (String(pin) !== DEMO_PIN) return { ok: false };
    new MockPaymentProvider(db).submit(p);
    return { ok: true, payment: p };
  }

  // ------------------------------------------------------------------
  // 7. Accounts, sessions, lockout
  // ------------------------------------------------------------------
  function toHex(buf) { return Array.prototype.map.call(new Uint8Array(buf), function (b) { return b.toString(16).padStart(2, '0'); }).join(''); }
  function fromHex(h) { var a = new Uint8Array(h.length / 2); for (var i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }

  async function hashPassword(password, saltHex, iterations) {
    var subtle = root.crypto && root.crypto.subtle;
    if (!subtle) throw new Error('This browser does not support Web Crypto, which Yogii needs for passwords.');
    var salt = saltHex ? fromHex(saltHex) : root.crypto.getRandomValues(new Uint8Array(16));
    var key = await subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
    var bits = await subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: salt, iterations: iterations }, key, 256);
    return { salt: toHex(salt), hash: toHex(bits), iterations: iterations };
  }

  function timingSafeEqual(a, b) {
    if (a.length !== b.length) return false;
    var r = 0;
    for (var i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return r === 0;
  }

  function validateRegistration(form, db) {
    var errors = {};
    var name = String(form.name || '').trim();
    var email = String(form.email || '').trim().toLowerCase();
    var phone = String(form.phone || '').trim();
    var pw = String(form.password || '');
    if (name.length < 2) errors.name = 'Enter your full name.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) errors.email = 'Enter a valid email address.';
    else if (findUserByEmail(db, email)) errors.email = 'This email can’t be used. Try another.';
    if (!/^[6-9][0-9]{9}$/.test(phone)) errors.phone = 'Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9.';
    else if (findUserByPhone(db, phone)) errors.phone = 'This mobile number can’t be used. Try another.';
    if (pw.length < 10 || !/[A-Z]/.test(pw) || !/[a-z]/.test(pw) || !/[0-9]/.test(pw)) errors.password = 'Use 10 or more characters with an uppercase letter, a lowercase letter and a number.';
    if (form.confirm !== undefined && form.confirm !== pw) errors.confirm = 'Passwords don’t match.';
    return errors;
  }

  function makeUpi(db, name) {
    var base = String(name).trim().split(/\s+/)[0].toLowerCase().replace(/[^a-z0-9]/g, '') || 'user';
    var upi = base + '@yogii', n = 1;
    while (findUserByUpi(db, upi) || directoryEntry(upi)) { n += 1; upi = base + n + '@yogii'; }
    return upi;
  }

  async function registerUser(db, form, options) {
    var errors = validateRegistration(form, db);
    if (Object.keys(errors).length) return { ok: false, errors: errors };
    var cred = await hashPassword(String(form.password), null, (options && options.iterations) || PBKDF2_ITERATIONS);
    var name = String(form.name).trim();
    var u = { id: 'u_' + simpleHash(form.email + now()).toLowerCase() + db.users.length, name: name, email: String(form.email).trim().toLowerCase(),
      upi: makeUpi(db, name), phone: String(form.phone).trim(), balance: START_BALANCE, createdAt: now(),
      salt: cred.salt, hash: cred.hash, iterations: cred.iterations, seeded: false, lastSignIn: null };
    db.users.push(u);
    return { ok: true, user: u };
  }

  var GENERIC_SIGNIN_ERROR = 'Email or password is incorrect.';

  async function signIn(db, email, password) {
    var key = String(email || '').trim().toLowerCase();
    var lock = db.lockouts[key] || { fails: 0, until: 0 };
    if (lock.until && now() < lock.until) {
      return { ok: false, locked: true, error: 'Too many attempts. Try again in ' + Math.ceil((lock.until - now()) / 1000) + ' seconds.' };
    }
    var u = findUserByEmail(db, key);
    var ok = false;
    if (u) {
      var cred = await hashPassword(String(password || ''), u.salt, u.iterations);
      ok = timingSafeEqual(cred.hash, u.hash);
    } else {
      await hashPassword(String(password || ''), '00000000000000000000000000000000', 1000); // similar work for unknown emails
    }
    if (!ok) {
      lock.fails = (lock.until && now() >= lock.until ? 0 : lock.fails) + 1;
      lock.until = 0;
      if (lock.fails >= MAX_FAILS) { lock.until = now() + LOCK_MS; lock.fails = 0; }
      db.lockouts[key] = lock;
      return { ok: false, locked: !!lock.until, error: lock.until ? 'Too many attempts. Try again in 60 seconds.' : GENERIC_SIGNIN_ERROR };
    }
    delete db.lockouts[key];
    u.previousSignIn = u.lastSignIn;
    u.lastSignIn = now();
    db.session = { userId: u.id, expiresAt: now() + SESSION_MS };
    return { ok: true, user: u };
  }

  function currentUser(db) {
    if (!db.session) return null;
    if (now() > db.session.expiresAt) { db.session = null; return null; }
    return findUser(db, db.session.userId);
  }

  // ------------------------------------------------------------------
  // Formatting helpers
  // ------------------------------------------------------------------
  var inrFmt = null;
  function inr(n, decimals) {
    try {
      if (!inrFmt) inrFmt = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 0 });
      return '₹' + inrFmt.format(decimals === 0 ? Math.floor(n) : n);
    } catch (e) { return '₹' + n; }
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtTime(t) {
    try { return new Date(t).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return new Date(t).toISOString(); }
  }
  function bandLabel(b) { return { LOW: 'Low', MEDIUM: 'Medium', HIGH: 'High', VERY_HIGH: 'Very high' }[b] || b; }
  function statusLabel(p) {
    if (p.status === 'FAILED' && p.decision === 'REJECTED') return 'Rejected';
    if (p.status === 'FAILED' && p.cancelled) return 'Cancelled';
    return { DRAFT: 'Draft', ASSESSING: 'Awaiting your decision', NEEDS_VERIFICATION: 'Needs verification', BLOCKED: 'Blocked',
      PENDING: 'Pending', COMPLETED: 'Completed', FAILED: 'Failed', REVERSED: 'Reversed' }[p.status] || p.status;
  }
  function levelOf(prob) { return prob < 0.3 ? 'Low' : prob < 0.6 ? 'Moderate' : 'High'; }

  // ------------------------------------------------------------------
  // Test hook
  // ------------------------------------------------------------------
  var api = {
    FEATURES: FEATURES, TRANSITIONS: TRANSITIONS, DEMO_CEILING: DEMO_CEILING, START_BALANCE: START_BALANCE, DIRECTORY: DIRECTORY,
    SEED_USERS: SEED_USERS, SEED_PAYMENTS: SEED_PAYMENTS,
    setNow: function (fn) { nowFn = fn; }, now: now,
    setModel: setModel, validateModel: validateModel, getModelError: function () { return MODEL_ERROR; },
    emptyDb: emptyDb, seedDb: seedDb, resolveRecipient: resolveRecipient, resolveKnown: resolveKnown,
    findUser: findUser, findUserByUpi: findUserByUpi, findPayment: findPayment,
    buildFeatures: buildFeatures, predictComponent: predictComponent, paymentChain: paymentChain, indirectPath: indirectPath,
    receiverRisk: receiverRisk, circularMeanHour: circularMeanHour, bandFor: bandFor, assess: assess, computeLimits: computeLimits,
    transition: transition, canTransition: canTransition, MockPaymentProvider: MockPaymentProvider,
    createPayment: createPayment, assessPayment: assessPayment, rejectPayment: rejectPayment, approvePayment: approvePayment,
    verifyPayment: verifyPayment, authorizePayment: authorizePayment,
    hashPassword: hashPassword, validateRegistration: validateRegistration, registerUser: registerUser, signIn: signIn, currentUser: currentUser
  };

  if (TEST) {
    setModel(TEST.model);
    TEST.api = api;
    return;
  }

  // ------------------------------------------------------------------
  // 8. UI
  // ------------------------------------------------------------------
  var doc = root.document;
  var db = null;
  var ui = { route: 'home', params: {}, flow: null, filters: { q: '', status: 'all', band: 'all' }, signinError: '', notice: '' };

  function save() { Storage.set(STORAGE_KEY, db); }

  async function loadDb() {
    var stored = Storage.get(STORAGE_KEY);
    if (stored && stored.version === DATA_VERSION && Array.isArray(stored.users) && Array.isArray(stored.payments)) return stored;
    var fresh = await seedDb();
    Storage.set(STORAGE_KEY, fresh);
    return fresh;
  }

  function readInlineModel() {
    var el = doc.getElementById('yogii-model');
    if (el && el.textContent.trim()) return Promise.resolve(JSON.parse(el.textContent));
    var src = el && el.getAttribute('data-src');
    if (!src || !root.fetch) return Promise.reject(new Error('Risk model file is missing.'));
    return root.fetch(src).then(function (r) { if (!r.ok) throw new Error('Risk model file is missing (' + r.status + ').'); return r.json(); });
  }

  function announce(msg) {
    var live = doc.getElementById('live');
    if (!live) return;
    live.textContent = '';
    setTimeout(function () { live.textContent = msg; }, 30);
  }

  function applyTheme() {
    var t = (db && db.prefs && db.prefs.theme) || 'system';
    if (t === 'system') doc.documentElement.removeAttribute('data-theme');
    else doc.documentElement.setAttribute('data-theme', t);
  }

  // ---------------- icons (inline SVG, decorative) ----------------
  var ICONS = {
    home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    send: '<path d="M4 12h14M13 6l6 6-6 6"/>',
    history: '<path d="M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4M12 8v4l3 2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/>',
    back: '<path d="M15 18l-6-6 6-6"/>',
    check: '<path d="M5 12l5 5 9-11"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    store: '<path d="M4 9l1-5h14l1 5M4 9v11h16V9M4 9h16M9 20v-6h6v6"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    alert: '<path d="M12 3l10 18H2zM12 10v5M12 18v.5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
  };
  function icon(name, cls) {
    return '<svg class="icon ' + (cls || '') + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + ICONS[name] + '</svg>';
  }

  function sim() { return '<span class="sim-tag">Simulated</span>'; }

  function bandChip(band) { return '<span class="chip band-' + band.toLowerCase() + '">' + esc(bandLabel(band)) + '</span>'; }
  function statusChip(p) { return '<span class="chip status-' + p.status.toLowerCase() + (p.decision === 'REJECTED' ? ' status-rejected' : '') + '">' + esc(statusLabel(p)) + '</span>'; }

  // ---------------- shell ----------------
  function shell(content, opts) {
    var user = currentUser(db);
    var nav = '';
    if (user) {
      var items = [['home', 'Home'], ['send', 'Send'], ['history', 'History'], ['settings', 'Settings']];
      var active = ui.route === 'payment' ? 'history' : ui.route;
      nav = '<nav class="nav" aria-label="Main">' + items.map(function (it) {
        return '<a href="#/' + it[0] + '" class="nav-item' + (active === it[0] ? ' active' : '') + '"' + (active === it[0] ? ' aria-current="page"' : '') + '>' + icon(it[0]) + '<span>' + it[1] + '</span></a>';
      }).join('') + '</nav>';
    }
    return '<div class="sim-banner" role="note">' + icon('shield') + '<span><strong>Simulation.</strong> No real money moves. Not connected to UPI, NPCI or any bank.</span></div>' +
      '<header class="topbar"><a class="brand" href="#/home" aria-label="Yogii home"><span class="logo" aria-hidden="true">Y</span><span>Yogii</span><span class="brand-sub">Risk Web</span></a>' +
      (user ? '<div class="topnav">' + nav + '</div>' : '') + '</header>' +
      '<main id="main" class="main' + (opts && opts.narrow ? ' narrow' : '') + '" tabindex="-1">' + content + '</main>' +
      (user ? '<div class="bottomnav">' + nav + '</div>' : '');
  }

  function render() {
    var app = doc.getElementById('app');
    if (!MODEL) {
      app.innerHTML = '<div class="sim-banner" role="note">' + icon('shield') + '<span><strong>Simulation.</strong> No real money moves.</span></div>' +
        '<main id="main" class="main narrow" tabindex="-1"><section class="card error-card" role="alert"><h1>Risk model unavailable</h1>' +
        '<p>Yogii can’t check payments because its risk model could not be loaded: <strong>' + esc(MODEL_ERROR || 'unknown error') + '</strong></p>' +
        '<p>Payments are disabled. Yogii never falls back to simpler rules. Rebuild the app with <code>python scripts/build.py</code>, or serve the folder over HTTP so <code>models/yogii_risk_model.json</code> can load.</p></section></main>';
      return;
    }
    var user = currentUser(db);
    if (!user && ui.route !== 'register') ui.route = 'signin';
    if (user && (ui.route === 'signin' || ui.route === 'register')) ui.route = 'home';
    var html;
    switch (ui.route) {
      case 'signin': html = shell(viewSignIn(), { narrow: true }); break;
      case 'register': html = shell(viewRegister(), { narrow: true }); break;
      case 'send': html = shell(viewSend(user)); break;
      case 'history': html = shell(viewHistory(user)); break;
      case 'payment': html = shell(viewPayment(user, ui.params.id)); break;
      case 'settings': html = shell(viewSettings(user)); break;
      default: html = shell(viewHome(user));
    }
    app.innerHTML = html;
    var focusEl = app.querySelector('[data-autofocus]') || app.querySelector('main h1');
    if (focusEl) {
      if (!focusEl.hasAttribute('tabindex') && !/INPUT|BUTTON|SELECT|TEXTAREA/.test(focusEl.tagName)) focusEl.setAttribute('tabindex', '-1');
      try { focusEl.focus({ preventScroll: false }); } catch (e) { /* ignore */ }
    }
  }

  function go(route, params) {
    ui.route = route; ui.params = params || {};
    var hash = '#/' + route + (params && params.id ? '/' + params.id : '');
    if (root.location.hash !== hash) { ui.skipHash = true; root.location.hash = hash; }
    render();
    try { root.scrollTo(0, 0); } catch (e) { /* ignore */ }
  }

  function onHash() {
    if (ui.skipHash) { ui.skipHash = false; return; }
    var parts = (root.location.hash || '').replace(/^#\/?/, '').split('/');
    var r = parts[0] || 'home';
    if (['home', 'send', 'history', 'payment', 'settings', 'signin', 'register'].indexOf(r) === -1) r = 'home';
    if (r === 'send' && ui.route !== 'send') ui.flow = null;
    ui.route = r; ui.params = r === 'payment' ? { id: parts[1] } : {};
    render();
  }

  // ---------------- auth views ----------------
  function field(id, label, type, opts) {
    opts = opts || {};
    var err = opts.error ? '<p class="field-error" id="' + id + '-err">' + esc(opts.error) + '</p>' : '';
    var hint = opts.hint ? '<p class="hint" id="' + id + '-hint">' + esc(opts.hint) + '</p>' : '';
    var describedBy = [opts.hint ? id + '-hint' : '', opts.error ? id + '-err' : ''].filter(Boolean).join(' ');
    return '<div class="field"><label for="' + id + '">' + esc(label) + '</label>' +
      '<input id="' + id + '" name="' + (opts.name || id) + '" type="' + type + '"' + (opts.value !== undefined ? ' value="' + esc(opts.value) + '"' : '') +
      (opts.autocomplete ? ' autocomplete="' + opts.autocomplete + '"' : '') + (opts.inputmode ? ' inputmode="' + opts.inputmode + '"' : '') +
      (opts.required !== false ? ' required' : '') + (opts.autofocus ? ' data-autofocus' : '') + (opts.maxlength ? ' maxlength="' + opts.maxlength + '"' : '') +
      (opts.placeholder ? ' placeholder="' + esc(opts.placeholder) + '"' : '') +
      (describedBy ? ' aria-describedby="' + describedBy + '"' : '') + (opts.error ? ' aria-invalid="true"' : '') + '>' + hint + err + '</div>';
  }

  function viewSignIn() {
    return '<section class="auth">' +
      '<div class="auth-head"><h1>Sign in</h1><p class="muted">Simulated payments with a prototype risk check.</p></div>' +
      '<form class="card form" data-form="signin" novalidate>' +
      field('si-email', 'Email', 'email', { name: 'email', autocomplete: 'username', autofocus: true, value: ui.lastEmail || '' }) +
      field('si-password', 'Password', 'password', { name: 'password', autocomplete: 'current-password' }) +
      '<p class="form-error" role="alert" id="signin-error">' + esc(ui.signinError) + '</p>' +
      '<button class="btn primary block" type="submit">Sign in</button>' +
      '<p class="center muted small">New here? <a href="#/register">Create a demo account</a></p></form>' +
      '<aside class="card demo-accounts"><h2>Demo accounts (fictional)</h2><ul>' +
      SEED_USERS.map(function (u) { return '<li><button type="button" class="linkish" data-action="fill-demo" data-email="' + u.email + '">' + esc(u.name) + '</button> <span class="muted mono">' + u.email + '</span></li>'; }).join('') +
      '</ul><p class="muted small">Password for all: <span class="mono">Password123!</span></p></aside></section>';
  }

  function viewRegister() {
    var e = ui.regErrors || {}, v = ui.regValues || {};
    return '<section class="auth"><div class="auth-head"><h1>Create a demo account</h1><p class="muted">New accounts start with a simulated ₹3,00,000.</p></div>' +
      '<form class="card form" data-form="register" novalidate>' +
      field('rg-name', 'Full name', 'text', { name: 'name', autocomplete: 'name', autofocus: true, error: e.name, value: v.name }) +
      field('rg-email', 'Email', 'email', { name: 'email', autocomplete: 'email', error: e.email, value: v.email }) +
      field('rg-phone', 'Mobile number', 'tel', { name: 'phone', autocomplete: 'tel-national', inputmode: 'numeric', maxlength: 10, error: e.phone, value: v.phone, hint: '10 digits, for example 98765 43210.' }) +
      field('rg-password', 'Password', 'password', { name: 'password', autocomplete: 'new-password', error: e.password, hint: 'At least 10 characters with uppercase, lowercase and a number.' }) +
      field('rg-confirm', 'Confirm password', 'password', { name: 'confirm', autocomplete: 'new-password', error: e.confirm }) +
      '<p class="form-error" role="alert">' + esc(ui.regError || '') + '</p>' +
      '<button class="btn primary block" type="submit">Create account</button>' +
      '<p class="center muted small">Have an account? <a href="#/signin">Sign in</a></p></form></section>';
  }

  // ---------------- home ----------------
  function userPayments(user) {
    return db.payments.filter(function (p) { return p.fromUserId === user.id || (p.to === user.upi && p.status === 'COMPLETED'); })
      .sort(function (a, b) { return b.createdAt - a.createdAt || b.seq - a.seq; });
  }

  function activityRow(p, user) {
    var incoming = p.to === user.upi && p.fromUserId !== user.id;
    var who = incoming ? p.fromName : p.toName;
    var sign = incoming ? '+' : (p.status === 'COMPLETED' ? '−' : '');
    return '<li><a class="row" href="#/payment/' + p.id + '">' +
      '<span class="avatar ' + (p.toType === 'merchant' && !incoming ? 'merchant' : '') + '" aria-hidden="true">' + esc((who || '?').charAt(0).toUpperCase()) + '</span>' +
      '<span class="row-main"><span class="row-title">' + esc(who) + '</span><span class="row-sub">' + (incoming ? 'Received · ' : '') + esc(fmtTime(p.createdAt)) + '</span></span>' +
      '<span class="row-end"><span class="amount ' + (incoming ? 'in' : '') + '">' + sign + esc(inr(p.amount)) + '</span>' +
      (incoming ? '<span class="chip status-completed">Received</span>' : statusChip(p)) + '</span></a></li>';
  }

  var SCENARIOS = [
    { title: 'Everyday payment', text: 'Pay rahul@upi ₹500: familiar recipient, low risk.', to: 'rahul@upi', amount: 500, who: 'yogesh' },
    { title: 'Unusual purchase', text: 'Pay techgadgets@merchant ₹24,500: high risk, needs verification.', to: 'techgadgets@merchant', amount: 24500, who: 'yogesh' },
    { title: 'Watchlisted receiver', text: 'Try crypto_drain@unknown: blocked, limit ₹0.', to: 'crypto_drain@unknown', amount: 1000, who: 'any' },
    { title: 'Payment chain, step 1', text: 'As Yogesh, pay visrojit@yogii ₹10,000.', to: 'visrojit@yogii', amount: 10000, who: 'yogesh' },
    { title: 'Payment chain, step 2', text: 'Sign in as Visrojit and pay dinesh@yogii ₹9,800: a 2-hop chain.', to: 'dinesh@yogii', amount: 9800, who: 'visrojit' },
    { title: 'Payment chain, step 3', text: 'Sign in as Dinesh and pay rahul@upi ₹9,500: a 3-hop chain, blocked.', to: 'rahul@upi', amount: 9500, who: 'dinesh' },
    { title: 'Indirect connection', text: 'Then, as Yogesh, pay dinesh@yogii to see the indirect path.', to: 'dinesh@yogii', amount: 2000, who: 'yogesh' }
  ];

  function viewHome(user) {
    var list = userPayments(user);
    var recent = list.slice(0, 5);
    var mine = db.payments.filter(function (p) { return p.fromUserId === user.id && !p.seeded; });
    var blocked = mine.filter(function (p) { return p.status === 'BLOCKED'; }).length;
    var verified = mine.filter(function (p) { return p.verification; }).length;
    var rejected = mine.filter(function (p) { return p.decision === 'REJECTED'; }).length;
    var hidden = db.prefs.hideBalance;
    var handle = user.upi.split('@')[0];
    var hints = SCENARIOS.filter(function (s) { return s.who === 'any' || s.who === handle || !user.seeded; });
    return '<h1 class="greeting">Hello, ' + esc(user.name.split(' ')[0]) + '</h1>' +
      '<div class="grid-home">' +
      '<section class="card balance-card" aria-labelledby="bal-h"><div class="balance-top"><h2 id="bal-h" class="label">Simulated balance</h2><span class="stamp" aria-hidden="true">SIMULATED</span></div>' +
      '<p class="balance" aria-live="polite">' + (hidden ? '<span aria-label="Balance hidden">₹ ••••••</span>' : esc(inr(user.balance))) + '</p>' +
      '<p class="muted small mono">' + esc(user.upi) + '</p>' +
      '<div class="actions"><a class="btn primary" href="#/send">' + icon('send') + 'Send money</a>' +
      '<button type="button" class="btn ghost" data-action="toggle-balance" aria-pressed="' + (hidden ? 'true' : 'false') + '">' + icon(hidden ? 'eye' : 'eyeOff') + (hidden ? 'Show balance' : 'Hide balance') + '</button></div></section>' +
      '<section class="card" aria-labelledby="sec-h"><h2 id="sec-h">Security summary</h2><ul class="facts">' +
      '<li><span>Last sign-in</span><strong>' + esc(user.previousSignIn ? fmtTime(user.previousSignIn) : 'First sign-in') + '</strong></li>' +
      '<li><span>Payments blocked</span><strong>' + blocked + '</strong></li>' +
      '<li><span>Payments you rejected</span><strong>' + rejected + '</strong></li>' +
      '<li><span>Demo verifications passed</span><strong>' + verified + '</strong></li>' +
      '<li><span>Session ends</span><strong>' + esc(fmtTime(db.session.expiresAt)) + '</strong></li></ul>' +
      '<p class="muted small">Every payment gets a risk check before you enter the demo PIN.</p></section>' +
      '<section class="card span-2" aria-labelledby="rec-h"><div class="card-head"><h2 id="rec-h">Recent activity</h2><a href="#/history" class="small">See all</a></div>' +
      (recent.length ? '<ul class="rows">' + recent.map(function (p) { return activityRow(p, user); }).join('') + '</ul>' : '<p class="muted">No payments yet.</p>') + '</section>' +
      '<section class="card span-2" aria-labelledby="scn-h"><h2 id="scn-h">Try a demo scenario</h2><p class="muted small">Fictional people and synthetic risk data. Tap one to pre-fill the payment.</p><ul class="scenarios">' +
      hints.map(function (s) {
        return '<li><button type="button" class="scenario" data-action="scenario" data-to="' + esc(s.to) + '" data-amount="' + s.amount + '"><strong>' + esc(s.title) + '</strong><span>' + esc(s.text) + '</span></button></li>';
      }).join('') + '</ul></section></div>';
  }

  // ---------------- send flow ----------------
  function newFlow() { return { step: 'recipient', input: '', recipient: null, amount: '', controls: { newDevice: false, night: false, outcome: 'success' }, error: '', paymentId: null, key: null }; }

  function flowPayment() { return ui.flow && ui.flow.paymentId ? findPayment(db, ui.flow.paymentId) : null; }

  function backLink(step, label) { return '<button type="button" class="btn ghost back" data-action="flow-back" data-step="' + step + '">' + icon('back') + (label || 'Back') + '</button>'; }

  function stepper(active) {
    var steps = ['Recipient', 'Amount', 'Risk check', 'Authorise', 'Result'];
    return '<ol class="stepper" aria-label="Payment steps">' + steps.map(function (s, i) {
      return '<li class="' + (i < active ? 'done' : i === active ? 'current' : '') + '"' + (i === active ? ' aria-current="step"' : '') + '><span>' + s + '</span></li>';
    }).join('') + '</ol>';
  }

  function viewSend(user) {
    if (!ui.flow) ui.flow = newFlow();
    var f = ui.flow;
    switch (f.step) {
      case 'confirm': return viewConfirmRecipient(user);
      case 'amount': return viewAmount(user);
      case 'risk': return viewRisk(user);
      case 'verify': return viewVerify(user);
      case 'pin': return viewPin(user);
      case 'processing': return '<section class="card center processing" aria-busy="true"><div class="spinner" aria-hidden="true"></div><h1>Processing</h1><p class="muted">Sending to the demo bank… ' + sim() + '</p></section>';
      case 'result': return viewResult(user);
      default: return viewRecipient(user);
    }
  }

  function viewRecipient(user) {
    var f = ui.flow;
    var saved = {};
    db.payments.forEach(function (p) { if (p.fromUserId === user.id && p.status === 'COMPLETED' && p.toType !== 'merchant') saved[p.to] = p.toName; });
    db.users.forEach(function (u) { if (u.id !== user.id) saved[u.upi] = u.name; });
    var people = Object.keys(saved).sort();
    var merchants = DIRECTORY.filter(function (d) { return d.type === 'merchant'; });
    return stepper(0) + '<h1>Send money</h1>' +
      '<form class="card form" data-form="recipient" novalidate>' +
      field('to-input', 'UPI ID or mobile number', 'text', { name: 'to', autofocus: true, value: f.input, error: f.error, autocomplete: 'off', placeholder: 'name@bank or 98765 43210', hint: 'Simulated: nothing is sent to a real UPI app.' }) +
      '<button class="btn primary block" type="submit">Continue</button></form>' +
      '<div class="grid-2"><section class="card"><h2>Saved people</h2><ul class="pick">' +
      people.map(function (upi) { return '<li><button type="button" class="pick-item" data-action="pick" data-to="' + esc(upi) + '"><span class="avatar" aria-hidden="true">' + esc(saved[upi].charAt(0)) + '</span><span><strong>' + esc(saved[upi]) + '</strong><span class="muted mono small">' + esc(upi) + '</span></span></button></li>'; }).join('') +
      '</ul></section><section class="card"><h2>Merchants</h2><ul class="pick">' +
      merchants.map(function (m) { return '<li><button type="button" class="pick-item" data-action="pick" data-to="' + esc(m.upi) + '"><span class="avatar merchant" aria-hidden="true">' + icon('store') + '</span><span><strong>' + esc(m.name) + '</strong><span class="muted mono small">' + esc(m.upi) + '</span></span></button></li>'; }).join('') +
      '</ul></section></div>';
  }

  function viewConfirmRecipient(user) {
    var r = ui.flow.recipient;
    var rr = receiverRisk(db, r, user.upi, now());
    var typeLabel = { user: 'Yogii account', merchant: 'Merchant', contact: 'UPI contact (demo directory)', unknown: 'Unverified account', unregistered: 'Not in the Yogii directory' }[r.type];
    return stepper(0) + backLink('recipient') + '<h1>Confirm recipient</h1>' +
      '<section class="card recipient-card"><span class="avatar lg ' + (r.type === 'merchant' ? 'merchant' : '') + '" aria-hidden="true">' + esc(r.name.charAt(0).toUpperCase()) + '</span>' +
      '<div><p class="recipient-name">' + esc(r.name) + '</p><p class="mono muted">' + esc(r.upi) + '</p><p class="small muted">' + esc(typeLabel) + '</p></div></section>' +
      '<section class="card"><h2>Receiver check</h2><p>' + levelPill(rr.level) + ' ' + esc(rr.note) + '</p>' +
      '<p class="muted small">For privacy you only see a level, never the receiver’s history or balance.</p></section>' +
      '<button type="button" class="btn primary block" data-action="confirm-recipient" data-autofocus>This is the right person</button>';
  }

  function levelPill(level) { return '<span class="pill level-' + level.toLowerCase() + '">' + esc(level) + '</span>'; }

  function currentLimits(user) {
    var f = ui.flow;
    var key = f.recipient.upi + '|' + f.controls.newDevice + '|' + f.controls.night + '|' + user.balance + '|' + db.payments.length;
    if (!f.limits || f.limitsKey !== key) { f.limits = computeLimits(db, { sender: user, recipient: f.recipient, controls: f.controls, at: now() }); f.limitsKey = key; }
    return f.limits;
  }

  function limitText(v, prevText) {
    if (v === null) return 'Up to the demo ceiling';
    if (v === 0) return prevText || 'Not available for this recipient';
    return 'Up to ' + inr(v);
  }

  function viewAmount(user) {
    var f = ui.flow, L = currentLimits(user), c = f.controls;
    var rows = [
      ['No extra checks', L.noChecks, 'Low risk: OK, then the demo PIN.'],
      ['With demo verification', L.verification, 'Medium risk: a short confirmation before the PIN.'],
      ['With a strong warning', L.strongWarning, 'High risk: a strong warning and verification.']
    ];
    var above = L.strongWarning === null ? 'No amount up to the demo ceiling is blocked by the model.' : L.strongWarning === 0 ? 'Every amount to this recipient is blocked.' : 'Above ' + inr(L.strongWarning) + ' the risk check blocks the payment.';
    return stepper(1) + backLink('confirm') + '<h1>Enter amount</h1>' +
      '<p class="muted">To <strong>' + esc(f.recipient.name) + '</strong> <span class="mono">' + esc(f.recipient.upi) + '</span></p>' +
      '<div class="grid-amount"><form class="card form" data-form="amount" novalidate>' +
      '<div class="field"><label for="amt">Amount (₹)</label><div class="amount-input"><span aria-hidden="true">₹</span><input id="amt" name="amount" type="text" inputmode="decimal" autocomplete="off" data-autofocus value="' + esc(f.amount) + '" aria-describedby="amt-hint' + (f.error ? ' amt-err' : '') + '"' + (f.error ? ' aria-invalid="true"' : '') + '></div>' +
      '<p class="hint" id="amt-hint">You can send up to ' + esc(inr(L.maxAllowed)) + ' here (demo ceiling ' + esc(inr(DEMO_CEILING)) + ', your simulated balance and the model limit).</p>' +
      (f.error ? '<p class="field-error" id="amt-err" role="alert">' + esc(f.error) + '</p>' : '') + '</div>' +
      field('note', 'Note (optional)', 'text', { name: 'note', required: false, maxlength: 80, value: f.note || '' }) +
      '<fieldset class="controls"><legend>Demo controls ' + sim() + '</legend>' +
      '<label class="toggle"><input type="checkbox" data-control="newDevice"' + (c.newDevice ? ' checked' : '') + '> Pretend this is a new device or location</label>' +
      '<label class="toggle"><input type="checkbox" data-control="night"' + (c.night ? ' checked' : '') + '> Pretend it’s 2 AM</label>' +
      '<div class="field"><label for="outcome">Demo bank outcome</label><select id="outcome" data-control="outcome">' +
      [['success', 'Success'], ['failure', 'Failure'], ['pending', 'Pending']].map(function (o) { return '<option value="' + o[0] + '"' + (c.outcome === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') +
      '</select></div></fieldset>' +
      '<button class="btn primary block" type="submit">Check risk</button></form>' +
      '<section class="card limits" aria-labelledby="lim-h" data-testid="limits"><h2 id="lim-h">Your limits for this recipient</h2>' +
      '<p class="muted small">Worked out by the risk model for this sender, recipient and the demo controls. Prototype values.</p>' +
      '<ul class="limit-rows">' + rows.map(function (r, i) {
        return '<li class="limit-row lr-' + i + '"><div><strong>' + r[0] + '</strong><span class="muted small">' + r[2] + '</span></div><span class="limit-val">' + esc(limitText(r[1])) + '</span></li>';
      }).join('') + '</ul><p class="limit-above' + (L.strongWarning === null ? '' : ' blocked') + '">' + icon(L.strongWarning === null ? 'shield' : 'alert') + '<span>' + esc(above) + '</span></p>' +
      '<p class="muted small">Also capped by the ' + esc(inr(DEMO_CEILING)) + ' demo ceiling and your simulated balance.</p></section></div>';
  }

  function bar(label, prob) {
    var pct = Math.round(prob * 100);
    var lvl = levelOf(prob);
    return '<div class="bar-row"><div class="bar-label"><span>' + esc(label) + '</span><span class="muted small">' + lvl + '</span></div>' +
      '<div class="bar" role="img" aria-label="' + esc(label) + ': ' + lvl + '"><span class="fill lvl-' + lvl.toLowerCase() + '" style="width:' + Math.max(3, pct) + '%"></span></div></div>';
  }

  function nameForChainNode(upi, user, links) {
    if (upi === user.upi) return 'You';
    // Only the account that paid the sender directly is named; earlier ones stay anonymous.
    var direct = links.length ? links[links.length - 1].from : null;
    if (upi === direct) { var u = findUserByUpi(db, upi); return u ? u.name : upi; }
    return 'Another Yogii account';
  }

  function chainView(risk, p, user) {
    var g = risk.graph;
    if (!g.hops) return '<p class="muted">No payment chain found: this payment doesn’t look like money you just received moving on.</p>';
    var steps = g.links.map(function (l) {
      return '<li><span class="node">' + esc(nameForChainNode(l.from, user, g.links)) + '</span><span class="edge">' + esc(inr(l.amount)) + ' · ' + Math.round(l.gapMinutes) + ' min before the next payment · ' + levelPill(l.level) + '</span></li>';
    }).join('') + '<li><span class="node">You</span><span class="edge">' + esc(inr(p.amount)) + ' · this payment</span></li><li><span class="node">' + esc(p.toName) + '</span></li>';
    return '<p><strong>' + g.hops + '-hop payment chain.</strong> Money seems to be moving through several accounts in similar amounts. This is a signal, not proof of anything.</p><ol class="chain">' + steps + '</ol>';
  }

  function indirectView(risk, user) {
    if (!risk.indirect.found) return '<p class="muted">No indirect connection found.</p>';
    var path = risk.indirect.path;
    var names = path.map(function (upi, i) {
      if (upi === user.upi) return 'You (' + upi + ')';
      if (i === path.length - 1) return upi;
      var paidDirectly = db.payments.some(function (q) { return q.fromUserId === user.id && q.to === upi && q.status === 'COMPLETED'; });
      return paidDirectly ? upi : 'Another Yogii account';
    });
    return '<p>You haven’t paid this recipient, but you’re connected through an intermediary you paid. This is a signal, not proof of anything.</p>' +
      '<p class="path" data-testid="indirect-path">' + names.map(function (n) { return '<span>' + esc(n) + '</span>'; }).join('<span aria-hidden="true" class="arrow">→</span>') + '</p>';
  }

  function riskBreakdown(p, user) {
    var r = p.risk;
    return '<div class="risk-grid">' +
      '<section class="card"><h2>Your side</h2>' + bar('Amount', r.components.amount) + bar('Behaviour', r.components.behavior) + bar('Context', r.components.context) + '</section>' +
      '<section class="card"><h2>Receiver side</h2><p>' + levelPill(r.receiver.level) + '</p><p>' + esc(r.receiver.note) + '</p><p class="muted small">You see only a level for privacy.</p></section>' +
      '<section class="card"><h2>Payment chain</h2>' + chainView(r, p, user) + '</section>' +
      '<section class="card"><h2>Indirect connection</h2>' + indirectView(r, user) + '</section>' +
      '<section class="card span-2"><h2>Why</h2>' + (r.reasons.length ? '<ul class="reasons">' + r.reasons.map(function (x) { return '<li data-code="' + x.code + '">' + icon('alert') + '<span>' + esc(x.text) + '</span></li>'; }).join('') + '</ul>' : '<p class="muted">Nothing unusual stood out.</p>') + '</section></div>';
  }

  function viewRisk(user) {
    var p = flowPayment();
    var r = p.risk;
    var blocked = p.status === 'BLOCKED';
    var msg = { LOW: 'Low risk. You can go ahead.', MEDIUM: 'Medium risk. We’ll ask for a short demo verification.', HIGH: 'High risk. Take a moment: make sure you know and trust this recipient.', VERY_HIGH: 'Very high risk. This payment is blocked.' }[r.band];
    return stepper(2) + '<h1>Risk check</h1>' +
      '<section class="card score-card band-bg-' + r.band.toLowerCase() + '" data-testid="risk-score"><div class="score"><span class="score-num">' + r.score + '</span><span class="score-of">/100</span></div>' +
      '<div><p>' + bandChip(r.band) + '</p><p class="score-msg">' + esc(msg) + '</p><p class="muted small">' + esc(inr(p.amount)) + ' to ' + esc(p.toName) + ' · prototype model on synthetic data</p></div></section>' +
      riskBreakdown(p, user) +
      '<section class="card decision" aria-labelledby="dec-h"><h2 id="dec-h">Before you enter your PIN</h2>' +
      (blocked ? '<p class="warn">' + icon('alert') + 'Yogii blocked this payment. No money moved. OK is disabled.</p>'
        : '<p>Check the name, amount and reasons above. Choose OK only if you know this recipient and nobody is pressuring you to pay.</p>') +
      '<div class="decide"><button type="button" class="btn ok" data-action="decide-ok"' + (blocked ? ' disabled aria-disabled="true"' : '') + '>' + icon('check') + 'OK</button>' +
      '<button type="button" class="btn reject" data-action="' + (blocked ? 'done-blocked' : 'decide-reject') + '">' + icon('x') + (blocked ? 'Close' : 'Reject') + '</button></div></section>';
  }

  function viewVerify(user) {
    var p = flowPayment();
    var high = p.risk.band === 'HIGH';
    var checks = ['I know this recipient personally or it’s a business I chose.', 'Nobody asked me to pay urgently or to “unlock” a refund, prize or job.'];
    if (high) checks.push('I understand that a simulated high-risk payment can’t be undone in real life.');
    return stepper(3) + '<h1>Demo verification</h1>' +
      '<form class="card form" data-form="verify" novalidate><p>' + bandChip(p.risk.band) + ' Confirm the following to continue. ' + sim() + '</p>' +
      '<fieldset><legend class="sr-only">Confirmations</legend>' + checks.map(function (c, i) { return '<label class="check"><input type="checkbox" name="c' + i + '" required' + (i === 0 ? ' data-autofocus' : '') + '> ' + esc(c) + '</label>'; }).join('') + '</fieldset>' +
      (high ? field('verify-upi', 'Type the recipient’s UPI ID to confirm', 'text', { name: 'upi', autocomplete: 'off', hint: 'Shown on the risk screen: ' + p.to }) : '') +
      '<p class="form-error" role="alert">' + esc(ui.flow.error || '') + '</p>' +
      '<p class="muted small">This is a demo step. Yogii never asks for an OTP.</p>' +
      '<div class="decide"><button class="btn primary" type="submit">Verify</button><button type="button" class="btn ghost" data-action="decide-reject">Cancel payment</button></div></form>';
  }

  function viewPin() {
    var p = flowPayment();
    return stepper(3) + '<h1>Enter demo PIN</h1>' +
      '<form class="card form pin-form" data-form="pin" novalidate autocomplete="off">' +
      '<p class="notice">' + icon('shield') + '<span><strong>This is not a UPI PIN.</strong> Use the demo PIN <span class="mono">1234</span>. Never type a real UPI PIN, OTP, CVV or bank password here.</span></p>' +
      '<p>' + esc(inr(p.amount)) + ' to <strong>' + esc(p.toName) + '</strong></p>' +
      '<div class="field"><label for="pin">Demo PIN</label><input id="pin" name="pin" type="password" inputmode="numeric" maxlength="4" autocomplete="off" data-autofocus aria-describedby="pin-hint' + (ui.flow.error ? ' pin-err' : '') + '"' + (ui.flow.error ? ' aria-invalid="true"' : '') + '>' +
      '<p class="hint" id="pin-hint">4 digits. Checked in memory, never saved.</p>' + (ui.flow.error ? '<p class="field-error" id="pin-err" role="alert">' + esc(ui.flow.error) + '</p>' : '') + '</div>' +
      '<div class="decide"><button class="btn primary" type="submit">Pay ' + esc(inr(p.amount)) + '</button><button type="button" class="btn ghost" data-action="decide-reject">Cancel payment</button></div></form>';
  }

  function viewResult(user) {
    var p = flowPayment();
    var title = { COMPLETED: 'Payment completed', FAILED: p.decision === 'REJECTED' ? 'Payment rejected' : 'Payment failed', PENDING: 'Payment pending', BLOCKED: 'Payment blocked' }[p.status] || statusLabel(p);
    var body = { COMPLETED: 'The simulated money has moved.', PENDING: 'The demo bank hasn’t confirmed yet. Your balance changes only once it completes.', FAILED: (p.failureReason || '') + ' Your balance did not change.', BLOCKED: 'No money moved.' }[p.status] || '';
    return stepper(4) + '<section class="card result result-' + p.status.toLowerCase() + '" data-testid="result"><div class="result-icon" aria-hidden="true">' + icon(p.status === 'COMPLETED' ? 'check' : p.status === 'PENDING' ? 'clock' : 'x') + '</div>' +
      '<h1>' + esc(title) + '</h1><p class="result-amount">' + esc(inr(p.amount)) + '</p><p>to ' + esc(p.toName) + ' <span class="mono muted">' + esc(p.to) + '</span></p>' +
      '<p class="muted">' + esc(body) + ' ' + sim() + '</p>' + (p.bankRef ? '<p class="small muted mono">Demo reference ' + esc(p.bankRef) + '</p>' : '') +
      '<div class="decide">' + (p.status === 'PENDING' ? '<button type="button" class="btn primary" data-action="check-status" data-id="' + p.id + '">Check status</button>' : '') +
      '<a class="btn ghost" href="#/payment/' + p.id + '">View details</a><button type="button" class="btn ghost" data-action="new-payment">New payment</button></div></section>';
  }

  // ---------------- history / detail ----------------
  function viewHistory(user) {
    var fl = ui.filters;
    var q = fl.q.trim().toLowerCase();
    var list = userPayments(user).filter(function (p) {
      if (fl.status !== 'all') {
        if (fl.status === 'REJECTED' ? p.decision !== 'REJECTED' : (p.status !== fl.status || (fl.status === 'FAILED' && p.decision === 'REJECTED'))) return false;
      }
      if (fl.band !== 'all' && (!p.risk || p.risk.band !== fl.band)) return false;
      if (q && [p.toName, p.to, p.fromName, p.from, String(p.amount), p.note || ''].join(' ').toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    var opt = function (v, l, cur) { return '<option value="' + v + '"' + (cur === v ? ' selected' : '') + '>' + l + '</option>'; };
    return '<h1>History</h1><form class="card filters" data-form="filters" role="search">' +
      '<div class="field"><label for="hq">Search</label><input id="hq" name="q" type="search" value="' + esc(fl.q) + '" placeholder="Name, UPI ID or amount"></div>' +
      '<div class="field"><label for="hs">Status</label><select id="hs" name="status">' + opt('all', 'All', fl.status) + opt('COMPLETED', 'Completed', fl.status) + opt('PENDING', 'Pending', fl.status) + opt('BLOCKED', 'Blocked', fl.status) + opt('FAILED', 'Failed', fl.status) + opt('REJECTED', 'Rejected', fl.status) + opt('NEEDS_VERIFICATION', 'Needs verification', fl.status) + '</select></div>' +
      '<div class="field"><label for="hb">Risk band</label><select id="hb" name="band">' + opt('all', 'All', fl.band) + BAND_ORDER.map(function (b) { return opt(b, bandLabel(b), fl.band); }).join('') + '</select></div></form>' +
      '<p class="muted small" aria-live="polite">' + list.length + ' payment' + (list.length === 1 ? '' : 's') + '</p>' +
      '<section class="card">' + (list.length ? '<ul class="rows">' + list.map(function (p) { return activityRow(p, user); }).join('') + '</ul>' : '<p class="muted">No payments match.</p>') + '</section>';
  }

  function viewPayment(user, id) {
    var p = findPayment(db, id);
    if (!p || (p.fromUserId !== user.id && p.to !== user.upi)) return '<h1>Payment not found</h1><p><a href="#/history">Back to history</a></p>';
    var incoming = p.fromUserId !== user.id;
    var head = '<a class="btn ghost back" href="#/history">' + icon('back') + 'History</a><h1>' + (incoming ? 'Payment received' : 'Payment to ' + esc(p.toName)) + '</h1>' +
      '<section class="card detail-head"><p class="result-amount">' + esc(inr(p.amount)) + '</p><p>' + (incoming ? statusChip({ status: 'COMPLETED' }) : statusChip(p)) + (p.risk && !incoming ? ' ' + bandChip(p.risk.band) : '') + ' ' + sim() + '</p>' +
      '<ul class="facts"><li><span>' + (incoming ? 'From' : 'To') + '</span><strong>' + esc(incoming ? p.fromName : p.toName) + ' <span class="mono muted">' + esc(incoming ? p.from : p.to) + '</span></strong></li>' +
      '<li><span>Created</span><strong>' + esc(fmtTime(p.createdAt)) + '</strong></li>' + (p.bankRef ? '<li><span>Demo reference</span><strong class="mono">' + esc(p.bankRef) + '</strong></li>' : '') +
      (p.note ? '<li><span>Note</span><strong>' + esc(p.note) + '</strong></li>' : '') + (p.failureReason && !incoming ? '<li><span>Reason</span><strong>' + esc(p.failureReason) + '</strong></li>' : '') + '</ul>' +
      (p.status === 'PENDING' && !incoming ? '<button type="button" class="btn primary" data-action="check-status" data-id="' + p.id + '">Check status</button>' : '') + '</section>';
    if (incoming) return head + '<p class="muted">Risk details are only shown to the sender.</p>';
    var timeline = '<section class="card"><h2>Timeline</h2><ol class="timeline">' + p.timeline.map(function (t) {
      return '<li><span class="t-status">' + esc(t.status.replace(/_/g, ' ').toLowerCase()) + '</span><span class="t-note">' + esc(t.note) + '</span><span class="t-time muted small">' + esc(fmtTime(t.at)) + '</span></li>';
    }).join('') + '</ol></section>';
    if (!p.risk) return head + timeline + '<p class="muted">Demo history entry: no risk check was stored.</p>';
    var r = p.risk;
    var tech = '<details class="card tech"><summary>Technical details</summary><p class="muted small">Prototype model trained on synthetic data (' + esc(r.model.engine) + ', v' + esc(r.model.version) + '). Component values are model probabilities.</p>' +
      '<table><caption class="sr-only">Risk inputs</caption><tbody>' +
      '<tr><th scope="row">Score</th><td>' + r.score + ' (' + esc(r.band) + ')</td></tr>' +
      '<tr><th scope="row">p_amount / p_behavior / p_context</th><td>' + [r.components.amount, r.components.behavior, r.components.context].map(function (x) { return x.toFixed(3); }).join(' / ') + '</td></tr>' +
      '<tr><th scope="row">graph / receiver</th><td>' + r.graph.score.toFixed(3) + ' / ' + r.receiver.score.toFixed(2) + '</td></tr>' +
      Object.keys(r.features).map(function (k) { var v = r.features[k]; return '<tr><th scope="row" class="mono">' + k + '</th><td class="mono">' + (Number.isInteger(v) ? v : v.toFixed(3)) + '</td></tr>'; }).join('') +
      '<tr><th scope="row">Demo controls</th><td>' + esc('new device: ' + (p.controls.newDevice ? 'yes' : 'no') + ', 2 AM: ' + (p.controls.night ? 'yes' : 'no') + ', bank: ' + p.controls.outcome) + '</td></tr>' +
      '</tbody></table></details>';
    return head + '<section class="card score-card band-bg-' + r.band.toLowerCase() + '"><div class="score"><span class="score-num">' + r.score + '</span><span class="score-of">/100</span></div><div>' + bandChip(r.band) + '<p class="muted small">Risk at the time of payment</p></div></section>' +
      timeline + riskBreakdown(p, user) + tech;
  }

  // ---------------- settings ----------------
  function viewSettings(user) {
    var m = MODEL;
    var theme = db.prefs.theme;
    var opt = function (v, l) { return '<option value="' + v + '"' + (theme === v ? ' selected' : '') + '>' + l + '</option>'; };
    return '<h1>Settings</h1><div class="grid-2">' +
      '<section class="card"><h2>Profile</h2><ul class="facts"><li><span>Name</span><strong>' + esc(user.name) + '</strong></li><li><span>Email</span><strong>' + esc(user.email) + '</strong></li>' +
      '<li><span>Mobile</span><strong>' + esc(user.phone) + '</strong></li><li><span>UPI ID</span><strong class="mono">' + esc(user.upi) + '</strong> ' + sim() + '</li></ul></section>' +
      '<section class="card"><h2>Security</h2><ul class="bullets"><li>Passwords are hashed with PBKDF2-SHA-256 and a per-user salt.</li><li>Sign-in locks for 60 seconds after 5 failed attempts.</li><li>Sessions last 12 hours. This one ends ' + esc(fmtTime(db.session.expiresAt)) + '.</li><li>The demo PIN is <span class="mono">1234</span>. It is not a UPI PIN and is never stored.</li></ul></section>' +
      '<section class="card"><h2>Privacy</h2><ul class="bullets"><li>Yogii never asks for or stores a UPI PIN, OTP, CVV, card PIN or bank password.</li><li>Your data stays in this browser (localStorage).</li><li>Receivers are shown to you only as a risk level.</li><li>In payment chains only the person who paid you directly is named.</li></ul></section>' +
      '<section class="card"><h2>Risk engine</h2><ul class="facts"><li><span>Model</span><strong>v' + esc(m.version) + ' · ' + esc(m.engine) + '</strong></li><li><span>Training data</span><strong>Synthetic only</strong></li>' +
      '<li><span>Components</span><strong>3 XGBoost anomaly models + graph + receiver side</strong></li><li><span>Combiner</span><strong>Linear regression</strong></li>' +
      '<li><span>Test PR-AUC (synthetic)</span><strong>' + esc(m.summary.pr_auc) + '</strong></li></ul>' +
      '<p class="muted small">Bands: 0–29 Low, 30–59 Medium, 60–84 High, 85–100 Very high (blocked). These are Yogii prototype values, not RBI, NPCI or bank standards. Graph links are signals, never proof of fraud.</p></section>' +
      '<section class="card"><h2>Appearance</h2><div class="field"><label for="theme">Theme</label><select id="theme" data-action-change="theme">' + opt('system', 'Match system') + opt('light', 'Light') + opt('dark', 'Dark') + '</select></div></section>' +
      '<section class="card"><h2>Session and data</h2><div class="stack"><button type="button" class="btn ghost" data-action="signout">Sign out</button>' +
      '<button type="button" class="btn danger" data-action="open-reset">Reset demo data</button></div><p class="muted small">Reset removes every account and payment in this browser and restores the fictional demo accounts.</p></section></div>' +
      '<dialog id="reset-dialog" aria-labelledby="reset-h" aria-describedby="reset-d"><form method="dialog" class="dialog-body"><h2 id="reset-h">Reset demo data?</h2><p id="reset-d">All accounts and payments in this browser will be removed and the demo accounts restored. You will be signed out.</p>' +
      '<div class="decide"><button value="cancel" class="btn ghost" data-autofocus-dialog>Cancel</button><button type="button" class="btn danger" data-action="confirm-reset">Reset</button></div></form></dialog>';
  }

  // ---------------- event handling ----------------
  function formData(form) {
    var out = {};
    Array.prototype.forEach.call(form.elements, function (el) { if (el.name) out[el.name] = el.type === 'checkbox' ? el.checked : el.value; });
    return out;
  }

  function parseAmount(s) {
    var t = String(s || '').replace(/[,\s₹]/g, '');
    if (!/^\d+(\.\d{1,2})?$/.test(t)) return NaN;
    return Number(t);
  }

  var busy = false;

  async function onSubmit(ev) {
    var form = ev.target.closest('form[data-form]');
    if (!form) return;
    ev.preventDefault();
    if (busy) return;
    var kind = form.getAttribute('data-form');
    var data = formData(form);
    var user = currentUser(db);
    try {
      busy = true;
      if (kind === 'signin') {
        ui.lastEmail = data.email;
        var btn = form.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Signing in…';
        var res = await signIn(db, data.email, data.password);
        save();
        if (!res.ok) { ui.signinError = res.error; render(); announce(res.error); return; }
        ui.signinError = ''; ui.flow = null; go('home'); announce('Signed in as ' + res.user.name);
      } else if (kind === 'register') {
        ui.regValues = { name: data.name, email: data.email, phone: data.phone };
        var rr = await registerUser(db, data);
        if (!rr.ok) { ui.regErrors = rr.errors; ui.regError = 'Please fix the highlighted fields.'; render(); announce('Please fix the highlighted fields.'); return; }
        ui.regErrors = null; ui.regValues = null; ui.regError = '';
        await signIn(db, data.email, data.password);
        save(); go('home'); announce('Account created. Your simulated UPI ID is ' + rr.user.upi);
      } else if (kind === 'recipient') {
        ui.flow.input = data.to;
        var r = resolveRecipient(db, data.to, user.id);
        if (r.error) { ui.flow.error = r.error; render(); announce(r.error); return; }
        ui.flow.error = ''; ui.flow.recipient = r.recipient; ui.flow.step = 'confirm'; render();
      } else if (kind === 'amount') {
        submitAmount(user, data);
      } else if (kind === 'verify') {
        var p = flowPayment();
        if (p.risk.band === 'HIGH' && String(data.upi || '').trim().toLowerCase() !== p.to) { ui.flow.error = 'The UPI ID doesn’t match. Check it on the risk screen.'; render(); announce(ui.flow.error); return; }
        var boxes = Array.prototype.filter.call(form.querySelectorAll('input[type=checkbox]'), function (c) { return !c.checked; });
        if (boxes.length) { ui.flow.error = 'Tick every confirmation to continue.'; render(); announce(ui.flow.error); return; }
        verifyPayment(p); save(); ui.flow.error = ''; ui.flow.step = 'pin'; render();
      } else if (kind === 'pin') {
        submitPin(user, form, data);
      }
    } catch (e) {
      showError(e);
    } finally { busy = false; }
  }

  function submitAmount(user, data) {
    var f = ui.flow;
    f.amount = data.amount; f.note = data.note;
    var a = parseAmount(data.amount);
    var L = currentLimits(user);
    var err = '';
    if (!(a > 0)) err = 'Enter an amount in rupees, for example 500 or 1250.50.';
    else if (a > DEMO_CEILING) err = 'That’s above the ' + inr(DEMO_CEILING) + ' demo ceiling.';
    else if (a > user.balance) err = 'That’s more than your simulated balance.';
    if (err) { f.error = err; render(); announce(err); return; }
    if (L.strongWarning !== null && a > L.strongWarning && !f.confirmOverLimit) {
      f.confirmOverLimit = true;
      f.error = 'Above the model limit for this recipient: the risk check will block it. Press Check risk again to see why.';
      render(); announce(f.error); return;
    }
    f.error = ''; f.confirmOverLimit = false;
    if (!f.key) f.key = 'k-' + user.id + '-' + now() + '-' + Math.random().toString(36).slice(2, 8);
    var p = createPayment(db, { senderId: user.id, recipient: f.recipient, amount: a, controls: f.controls, key: f.key, note: data.note });
    if (p.status === 'DRAFT') assessPayment(db, p);
    save();
    f.paymentId = p.id; f.step = 'risk'; render();
    announce('Risk check: ' + p.risk.score + ' out of 100, ' + bandLabel(p.risk.band) + ' risk.');
  }

  function submitPin(user, form, data) {
    var p = flowPayment();
    var res = authorizePayment(db, p, data.pin);
    form.reset();
    if (!res.ok) {
      ui.flow.pinFails = (ui.flow.pinFails || 0) + 1;
      if (ui.flow.pinFails >= 3) { rejectPayment(p, 'Cancelled after 3 wrong demo PIN attempts.'); p.decision = null; save(); ui.flow.step = 'result'; render(); return; }
      ui.flow.error = 'Wrong demo PIN. The demo PIN is 1234. ' + (3 - ui.flow.pinFails) + ' attempt' + (3 - ui.flow.pinFails === 1 ? '' : 's') + ' left.';
      render(); announce(ui.flow.error); return;
    }
    ui.flow.error = '';
    save();
    ui.flow.step = 'processing'; render();
    setTimeout(function () { ui.flow.step = 'result'; render(); announce(statusLabel(p) + ': ' + inr(p.amount) + ' to ' + p.toName); }, 700);
  }

  function showError(e) {
    var msg = (e && e.message) || 'Something went wrong.';
    if (ui.flow) { ui.flow.error = msg; }
    render(); announce(msg);
  }

  function onClick(ev) {
    var el = ev.target.closest('[data-action]');
    if (!el || el.disabled) return;
    var a = el.getAttribute('data-action');
    var user = currentUser(db);
    try {
      switch (a) {
        case 'fill-demo': {
          var email = doc.getElementById('si-email'); email.value = el.getAttribute('data-email');
          doc.getElementById('si-password').focus(); break;
        }
        case 'toggle-balance': db.prefs.hideBalance = !db.prefs.hideBalance; save(); render(); announce(db.prefs.hideBalance ? 'Balance hidden' : 'Balance shown'); break;
        case 'scenario':
          ui.flow = newFlow();
          var sr = resolveRecipient(db, el.getAttribute('data-to'), user.id);
          if (sr.error) { ui.flow.input = el.getAttribute('data-to'); ui.flow.error = sr.error; }
          else { ui.flow.recipient = sr.recipient; ui.flow.input = sr.recipient.upi; ui.flow.amount = el.getAttribute('data-amount'); ui.flow.step = 'confirm'; }
          go('send'); break;
        case 'pick': {
          var pr = resolveRecipient(db, el.getAttribute('data-to'), user.id);
          if (pr.error) { ui.flow.error = pr.error; render(); break; }
          ui.flow.input = pr.recipient.upi; ui.flow.recipient = pr.recipient; ui.flow.error = ''; ui.flow.step = 'confirm'; render(); break;
        }
        case 'confirm-recipient': ui.flow.step = 'amount'; ui.flow.error = ''; render(); break;
        case 'flow-back': ui.flow.step = el.getAttribute('data-step'); ui.flow.error = ''; ui.flow.confirmOverLimit = false; render(); break;
        case 'decide-ok': {
          var p = flowPayment();
          approvePayment(p); save();
          ui.flow.step = p.status === 'NEEDS_VERIFICATION' ? 'verify' : 'pin'; ui.flow.error = ''; render(); break;
        }
        case 'decide-reject': {
          var rp = flowPayment();
          rejectPayment(rp); save(); ui.flow.step = 'result'; render(); announce('Payment rejected. No money moved.'); break;
        }
        case 'done-blocked': ui.flow.step = 'result'; render(); break;
        case 'new-payment': ui.flow = newFlow(); go('send'); break;
        case 'check-status': {
          var cp = findPayment(db, el.getAttribute('data-id'));
          var res = new MockPaymentProvider(db).callback(cp); save(); render();
          announce(res.duplicate ? 'Already ' + statusLabel(cp).toLowerCase() + '. Nothing changed.' : 'Status: ' + statusLabel(cp)); break;
        }
        case 'signout': db.session = null; save(); ui.flow = null; go('signin'); announce('Signed out'); break;
        case 'open-reset': {
          var dlg = doc.getElementById('reset-dialog');
          if (dlg && dlg.showModal) { dlg.showModal(); var c = dlg.querySelector('[data-autofocus-dialog]'); if (c) c.focus(); }
          else if (root.confirm('Reset demo data?')) resetAll();
          break;
        }
        case 'confirm-reset': resetAll(); break;
      }
    } catch (e) { showError(e); }
  }

  async function resetAll() {
    var d = doc.getElementById('reset-dialog'); if (d && d.open) d.close();
    Storage.remove(STORAGE_KEY);
    db = await seedDb(); save(); ui.flow = null; ui.filters = { q: '', status: 'all', band: 'all' };
    go('signin'); announce('Demo data reset.');
  }

  function onChange(ev) {
    var el = ev.target;
    if (el.hasAttribute('data-control') && ui.flow) {
      var k = el.getAttribute('data-control');
      ui.flow.controls[k] = el.type === 'checkbox' ? el.checked : el.value;
      var amt = doc.getElementById('amt'); if (amt) ui.flow.amount = amt.value;
      var note = doc.getElementById('note'); if (note) ui.flow.note = note.value;
      ui.flow.confirmOverLimit = false;
      render();
      var again = doc.querySelector('[data-control="' + k + '"]'); if (again) again.focus();
      announce('Limits updated.');
      return;
    }
    if (el.getAttribute('data-action-change') === 'theme') { db.prefs.theme = el.value; save(); applyTheme(); announce('Theme changed'); return; }
    var form = el.closest('form[data-form="filters"]');
    if (form) { updateFilters(form, el); }
  }

  function onInput(ev) {
    var form = ev.target.closest('form[data-form="filters"]');
    if (form && ev.target.name === 'q') updateFilters(form, ev.target);
  }

  function updateFilters(form, el) {
    var d = formData(form);
    ui.filters = { q: d.q || '', status: d.status || 'all', band: d.band || 'all' };
    var id = el.id, pos = el.selectionStart;
    render();
    var again = doc.getElementById(id);
    if (again) { again.focus(); try { if (pos !== null && again.setSelectionRange) again.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } }
  }

  async function boot() {
    try { setModel(await readInlineModel()); } catch (e) { MODEL = null; MODEL_ERROR = e.message; }
    try { db = await loadDb(); } catch (e) { db = emptyDb(); MODEL_ERROR = MODEL_ERROR || null; }
    applyTheme();
    doc.addEventListener('submit', onSubmit);
    doc.addEventListener('click', onClick);
    doc.addEventListener('change', onChange);
    doc.addEventListener('input', onInput);
    root.addEventListener('hashchange', onHash);
    onHash();
    root.__YOGII_READY__ = true;
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot); else boot();
})(typeof window !== 'undefined' ? window : globalThis);
