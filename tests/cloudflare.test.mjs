// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import * as backend from '../cloudflare/worker.mjs';
import {PairingState} from '../cloudflare/state.mjs';
const ORIGIN = 'https://example.github.io';
const profile = n => ({firmware: String(n % 10).repeat(64), transport: 'f'.repeat(64)});
const token = n => n.toString(16).padStart(64, '0');
const packet = (seq, value = seq) => ({seq, words: [value, 0, 65535, 4660, 43981, 2, 3, 4]});
function harness(options = {}) {
  const db = new DatabaseSync(':memory:');
  const storage = {
    sql: {exec(query, ...values) {
      if (!values.length && query.includes(';')) {db.exec(query); return {toArray: () => []};}
      const rows = db.prepare(query).all(...values); return {toArray: () => rows};
    }},
    transactionSync(fn) {
      db.exec('BEGIN');
      try {const result = fn(); db.exec('COMMIT'); return result;}
      catch (error) {db.exec('ROLLBACK'); throw error;}
    },
  };
  const env = {ALLOWED_ORIGINS: ORIGIN, ...options.env};
  let now = 1_800_000_000_000, state;
  try {state = new PairingState(storage, env);} catch (error) {db.close(); throw error;}
  const bindings = {...env, PAIRING: {idFromName: name => name, get: () => ({fetch: request =>
    backend.handleLink(request, state, env, {now: () => now})})}};
  const request = async (body, opt = {}) => {
    const response = await backend.default.fetch(new Request(`https://pair.example${opt.path || '/api/link'}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', Origin: ORIGIN,
        'CF-Connecting-IP': opt.ip || '192.0.2.1', ...opt.headers}, body: opt.raw ?? JSON.stringify(body),
    }), bindings);
    return {status: response.status, body: await response.json(), headers: response.headers};
  };
  const create = async (n, opt) => {
    const result = await request({action: 'create', code: null, token: token(n), profile: profile(n)}, opt);
    assert.equal(result.status, 200, JSON.stringify(result.body));
    return {code: result.body.code, token: token(n), profile: profile(n)};
  };
  const exchange = (member, fields = {}, opt) => request({...member, action: 'exchange', received: 0, packets: [], ...fields}, opt);
  return {request, create, exchange, bindings, db, advance: ms => {now += ms;},
    restart: () => {state = new PairingState(storage, env);}, close: () => db.close()};
}
async function paired(h) {
  const a = await h.create(1), b = await h.create(2);
  const r = await h.request({...a, action: 'pair', peer: b.code});
  assert.equal(r.status, 200, JSON.stringify(r.body)); return {a, b, code: r.body.code};
}

test('create is idempotent across restart and persists no private tokens or raw IPs', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1); h.restart();
  const again = await h.request({...a, code: null, action: 'create'});
  assert.equal(again.status, 200); assert.equal(again.body.code, a.code);
  assert.equal(again.body.expires, 1_800_001_800_000); assert.equal(again.body.connected, false);
  assert.equal(again.body.accepted, 0); assert.deepEqual(again.body.packets, []);
  const tables = h.db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all();
  const stored = JSON.stringify(tables.flatMap(({name}) => h.db.prepare(`SELECT * FROM ${name}`).all()));
  assert.ok(!stored.includes(token(1))); assert.ok(!stored.includes('192.0.2.1'));
  assert.equal((await h.request({...a, code: null, action: 'create', profile: profile(9)})).status, 409);
});
test('reciprocal scans choose smaller code and stable slots despite different firmware', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1), b = await h.create(2);
  const rs = await Promise.all([h.request({...a, action: 'pair', peer: b.code}), h.request({...b, action: 'pair', peer: a.code})]);
  for (const r of rs) {assert.equal(r.status, 200); assert.equal(r.body.code, [a.code, b.code].sort()[0]); assert.equal(r.body.connected, true);}
  assert.notEqual(rs[0].body.slot, rs[1].body.slot); assert.deepEqual(rs[0].body.peerProfile, b.profile);
  assert.equal((await h.request({...a, action: 'pair', peer: b.code})).body.slot, rs[0].body.slot);
});
test('own authentication precedes peer lookup and a third phone cannot enter either alias', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h), c = await h.create(3);
  assert.equal((await h.request({...a, token: c.token, action: 'pair', peer: '22222222'})).status, 403);
  for (const code of [a.code, b.code]) {
    assert.equal((await h.request({...c, action: 'pair', peer: code})).status, 409);
    assert.equal((await h.exchange({...c, code})).status, 403);
    assert.equal((await h.request({...c, code, action: 'leave'})).status, 403);
  }
  assert.equal((await h.exchange(a)).body.connected, true);
});
test('self and incompatible transport pairing fail without admitting unpaired sends', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1);
  const b = await h.request({action: 'create', code: null, token: token(2), profile: {...profile(2), transport: 'e'.repeat(64)}});
  assert.equal((await h.request({...a, action: 'pair', peer: a.code})).status, 409);
  assert.equal((await h.request({...a, action: 'pair', peer: b.body.code})).status, 409);
  assert.equal((await h.exchange(a)).body.connected, false);
  assert.equal((await h.exchange(a, {packets: [packet(1)]})).status, 409);
  assert.equal((await h.exchange(a, {received: 1})).status, 409);
});
test('native words arrive intact; accepted advances only after peer-received ACK', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  const sent = await h.exchange(a, {packets: [packet(1)]}); assert.equal(sent.status, 200); assert.equal(sent.body.accepted, 0);
  assert.deepEqual((await h.exchange(b)).body.packets, [{seq: 1, words: [1, 0, 65535, 4660, 43981, 2, 3, 4]}]);
  assert.equal((await h.exchange(a)).body.accepted, 0);
  assert.equal((await h.exchange(b, {received: 1})).status, 200);
  assert.equal((await h.exchange(a)).body.accepted, 1); h.restart();
  assert.equal((await h.exchange(a)).body.accepted, 1);
  assert.deepEqual((await h.exchange(b, {received: 1})).body.packets, []);
});
test('exact retries succeed; changed replay, duplicate sequence, and gaps fail atomically', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  for (let i = 0; i < 2; i++) assert.equal((await h.exchange(a, {packets: [packet(1), packet(2)]})).status, 200);
  for (const packets of [[packet(2, 99)], [packet(4)], [packet(3), packet(5)], [packet(3), packet(3)]])
    assert.equal((await h.exchange(a, {packets})).status, 409);
  assert.deepEqual((await h.exchange(b)).body.packets, [packet(1), packet(2)]);
  assert.equal((await h.exchange(a, {packets: [packet(2), packet(3)]})).status, 200);
  assert.deepEqual((await h.exchange(b)).body.packets, [packet(1), packet(2), packet(3)]);
});
test('ACK cannot decrease or exceed peer sends, and failed writes roll back ACK', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  assert.equal((await h.exchange(b, {received: 1})).status, 409);
  await h.exchange(a, {packets: [packet(1), packet(2)]});
  assert.equal((await h.exchange(b, {received: 1})).status, 200);
  for (const received of [0, 3]) assert.equal((await h.exchange(b, {received})).status, 409);
  assert.equal((await h.exchange(b, {received: 2, packets: [packet(2)]})).status, 409);
  assert.equal((await h.exchange(a)).body.accepted, 1);
  assert.deepEqual((await h.exchange(b, {received: 1})).body.packets, [packet(2)]);
});
test('512 packets per member persist individually, delivered in batches of at most16', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  for (const member of [a, b]) for (let start = 1; start <= 512; start += 16)
    assert.equal((await h.exchange(member, {packets: Array.from({length: 16}, (_, i) => packet(start + i))})).status, 200);
  h.restart();
  for (let received = 0; received < 512; received += 16) {
    const r = await h.exchange(b, {received}); assert.equal(r.status, 200); assert.equal(r.body.packets.length, 16);
    assert.equal(r.body.packets[0].seq, received + 1); assert.equal(r.body.packets.at(-1).seq, received + 16);
    assert.ok(new TextEncoder().encode(JSON.stringify(r.body)).length <= 8192);
  }
  assert.equal((await h.exchange(b, {received: 512})).status, 200); assert.equal((await h.exchange(a)).body.accepted, 512);
  assert.equal((await h.exchange(a, {packets: [packet(513)]})).status, 400);
  const rows = h.db.prepare("SELECT value FROM pairing_records WHERE key LIKE 'packet:%'").all();
  assert.equal(rows.length, 1024); assert.ok(rows.every(row => new TextEncoder().encode(row.value).length < 256));
});
test('strict packet and cursor schema rejects malformed payloads without storing prefixes', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  const invalid = [{received: -1}, {received: 513}, {received: 0.5}, {received: '0'}, {packets: null},
    {packets: Array.from({length: 17}, (_, i) => packet(i + 1))},
    ...[0, 513, 0.5, '1'].map(seq => ({packets: [{...packet(1), seq}]})),
    ...[null, [], Array(7).fill(0), Array(9).fill(0), ...[-1, 65536, 0.5, '1'].map(v => [0, 0, 0, 0, 0, 0, 0, v])]
      .map(words => ({packets: [{seq: 1, words}]})), {packets: [{...packet(1), rom: 'no'}]}, {packets: [packet(1), null]}, {rom: 'no'}];
  for (const fields of invalid) assert.equal((await h.exchange(a, fields)).status, 400, JSON.stringify(fields));
  for (const missing of ['received', 'packets']) {
    const body = {...a, action: 'exchange', received: 0, packets: []}; delete body[missing];
    assert.equal((await h.request(body)).status, 400);
  }
  assert.deepEqual((await h.exchange(b)).body.packets, []);
});
test('leave closes aliases idempotently and suppresses queued and new packets', async t => {
  const h = harness(); t.after(h.close); const {a, b} = await paired(h);
  await h.exchange(a, {packets: [packet(1)]});
  for (let i = 0; i < 2; i++) assert.equal((await h.request({...b, action: 'leave'})).body.closed, true);
  const r = await h.exchange(a, {packets: [packet(2)]}); assert.equal(r.status, 200);
  assert.equal(r.body.closed, true); assert.equal(r.body.connected, false); assert.deepEqual(r.body.packets, []);
  assert.deepEqual((await h.exchange(b)).body.packets, []);
  assert.equal((await h.request({...a, action: 'pair', peer: b.code})).status, 409);
});
test('presence begins at merge; peer absence over20 seconds closes permanently across restart', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1); h.advance(60_000); const b = await h.create(2);
  await h.request({...a, action: 'pair', peer: b.code}); h.advance(20_000);
  assert.equal((await h.exchange(a)).body.connected, true); h.advance(1);
  const r = await h.exchange(a, {packets: [packet(1)]}); assert.equal(r.body.closed, true); assert.deepEqual(r.body.packets, []);
  h.restart(); assert.equal((await h.exchange(b)).body.closed, true);
  assert.equal((await h.request({...a, code: null, action: 'create'})).body.closed, true);
});
test('merged TTL is the earlier invitation; expired aliases cannot revive', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1); h.advance(60_000); const b = await h.create(2);
  assert.equal((await h.request({...b, action: 'pair', peer: a.code})).body.expires, 1_800_001_800_000);
  h.advance(1_740_000); for (const member of [a, b]) assert.equal((await h.exchange(member)).status, 404);
  const fresh = await h.create(1); assert.notEqual(fresh.code, a.code);
  assert.equal((await h.request({...b, action: 'pair', peer: fresh.code})).status, 404);
});
test('reused canonical code cannot resolve an old identity-bound alias', async t => {
  const h = harness(); t.after(h.close); const {a, b, code} = await paired(h), alias = a.code === code ? b : a;
  const replacement = JSON.parse(h.db.prepare('SELECT value FROM pairing_records WHERE key=?').get(`room:${code}`).value);
  replacement.id = 'new-session'; h.db.prepare('UPDATE pairing_records SET value=? WHERE key=?').run(JSON.stringify(replacement), `room:${code}`);
  assert.equal((await h.exchange(alias)).status, 404);
});
test('IP request limits survive restart and reset at their minute boundary', async t => {
  const h = harness({env: {REQUESTS_PER_IP_MINUTE: '2'}}); t.after(h.close); const a = await h.create(1);
  assert.equal((await h.exchange(a)).status, 200); h.restart(); assert.equal((await h.exchange(a)).status, 429);
  assert.equal((await h.exchange(a, {}, {ip: '192.0.2.2'})).status, 200); h.advance(60_000);
  assert.equal((await h.exchange(a)).status, 200);
});
test('global quota charges malformed posts, survives restart and resets by UTC day', async t => {
  const h = harness({env: {REQUESTS_GLOBAL_DAY: '3'}}); t.after(h.close); const a = await h.create(1);
  assert.equal((await h.request(null, {raw: '{broken'})).status, 400);
  assert.equal((await h.exchange(a, {}, {ip: '192.0.2.2'})).status, 200); h.restart();
  assert.equal((await h.exchange(a, {}, {ip: '192.0.2.3'})).status, 429); h.advance(86_400_000); await h.create(2);
});
test('creation quotas persist without double-charging retries and share a global cap across IPs', async t => {
  const h = harness({env: {CREATE_PER_IP_HOUR: '2', CREATE_PER_IP_DAY: '3', CREATE_GLOBAL_DAY: '4'}}); t.after(h.close);
  const a = await h.create(1); await h.create(2); h.restart();
  assert.equal((await h.request({...a, code: null, action: 'create'})).status, 200);
  assert.equal((await h.request({action: 'create', token: token(3), code: null, profile: profile(3)})).status, 429);
  await h.create(3, {ip: '192.0.2.2'}); await h.create(4, {ip: '192.0.2.2'});
  assert.equal((await h.request({action: 'create', token: token(5), code: null, profile: profile(5)}, {ip: '192.0.2.3'})).status, 429);
});
test('configured quotas cannot exceed the conservative Free trial ceilings', () => {
  for (const [name, value] of Object.entries({REQUESTS_PER_IP_MINUTE: '601', REQUESTS_GLOBAL_DAY: '8001',
    CREATE_PER_IP_HOUR: '11', CREATE_PER_IP_DAY: '21', CREATE_GLOBAL_DAY: '501'}))
    assert.throws(() => harness({env: {[name]: value}}), error => error.status === 503, name);
});
test('removed signaling and ICE paths reject requests without external network calls', async t => {
  const h = harness(); t.after(h.close); const {a} = await paired(h); const original = globalThis.fetch; let egress = 0;
  globalThis.fetch = async () => {egress++; throw Error('external fetch prohibited');};
  try {
    for (const action of ['ice', 'signal', 'poll']) assert.equal((await h.request({...a, action})).status, 400);
    assert.equal((await h.request({...a, action: 'ice'}, {path: '/api/signaling'})).status, 404);
    assert.equal((await h.exchange(a, {packets: [packet(1)]})).status, 200); assert.equal(egress, 0);
  } finally {globalThis.fetch = original;}
});
test('HTTP enforces exact origin, POST, JSON,8KiB and600 second preflight cache', async t => {
  const h = harness(); t.after(h.close); const a = await h.create(1);
  for (const body of [null, [], {...a, action: 'unknown'}, {...a, action: 'create', code: null, profile: {...a.profile, rom: 'no'}},
    {...a, action: 'create', code: null, profile: {firmware: ['a'.repeat(64)], transport: 'f'.repeat(64)}}, {...a, token: 'bad', action: 'leave'}])
    assert.equal((await h.request(body)).status, 400);
  for (const origin of ['', `${ORIGIN}.evil.example`, `${ORIGIN}/`, 'https://evil.example'])
    assert.equal((await h.exchange(a, {}, {headers: {Origin: origin}})).status, 403);
  for (const raw of ['x'.repeat(8193), JSON.stringify({x: '界'.repeat(3000)})]) assert.equal((await h.request(null, {raw})).status, 413);
  assert.equal((await h.request(null, {raw: '{broken'})).status, 400);
  assert.equal((await h.exchange(a, {}, {headers: {'Content-Type': 'text/plain'}})).status, 400);
  assert.equal((await h.exchange(a)).headers.get('Cache-Control'), 'no-store');
  const preflight = await backend.default.fetch(new Request('https://pair.example/api/link', {method: 'OPTIONS', headers: {
    Origin: ORIGIN, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'}}), h.bindings);
  assert.equal(preflight.status, 204); assert.equal(preflight.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.equal(preflight.headers.get('Access-Control-Max-Age'), '600');
  assert.equal((await backend.default.fetch(new Request('https://pair.example/api/link', {headers: {Origin: ORIGIN}}), h.bindings)).status, 400);
  assert.equal((await backend.default.fetch(new Request('https://pair.example/api/link', {method: 'POST', headers: {Origin: ORIGIN}}), {ALLOWED_ORIGINS: ORIGIN})).status, 503);
});
test('Durable Object failure remains a readable terminal503 for an allowed browser origin', async () => {
  const bindings = {ALLOWED_ORIGINS: ORIGIN, PAIRING: {idFromName: name => name, get: () => ({fetch: async () => {throw Error('private platform detail');}})}};
  const r = await backend.default.fetch(new Request('https://pair.example/api/link', {method: 'POST', headers: {Origin: ORIGIN}}), bindings);
  assert.equal(r.status, 503); assert.equal(r.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.equal(r.headers.get('Cache-Control'), 'no-store'); assert.deepEqual(await r.json(), {error: 'Link service unavailable.'});
});
