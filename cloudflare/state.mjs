// SPDX-License-Identifier: GPL-3.0-or-later
// Persisted synchronous transitions. Never await inside a transaction.
export const SESSION_TTL = 30 * 60 * 1000;
export const MAX_BODY = 8 * 1024;
const PEER_TIMEOUT = 20 * 1000;
const HEX = /^[0-9a-f]{64}$/;
const CODE = /^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const integer = (value, min, max) => Number.isSafeInteger(value) && value >= min && value <= max;
export class ServiceError extends Error {
  constructor(message, status = 400) {super(message); this.status = status;}
}
const fail = (message, status) => {throw new ServiceError(message, status);};
function keys(value, allowed, required = []) {
  if (!object(value) || Object.keys(value).some(key => !allowed.includes(key)) || required.some(key => !Object.hasOwn(value, key))) fail('Invalid request shape.');
}
function checkedProfile(value) {
  keys(value, ['firmware', 'transport'], ['firmware', 'transport']);
  if (typeof value.firmware !== 'string' || typeof value.transport !== 'string' || !HEX.test(value.firmware) || !HEX.test(value.transport)) fail('Invalid connection profile.');
  return {firmware: value.firmware, transport: value.transport};
}
function checkedPacket(value) {
  keys(value, ['seq', 'words'], ['seq', 'words']);
  if (!integer(value.seq, 1, 512) || !Array.isArray(value.words) || value.words.length !== 8 || value.words.some(word => !integer(word, 0, 65535))) fail('Invalid native packet.');
  return {seq: value.seq, words: [...value.words]};
}
export function validateBody(value) {
  const fields = {create: [], pair: ['peer'], exchange: ['received', 'packets'], leave: []};
  if (!object(value) || !Object.hasOwn(fields, value.action)) fail('Unknown link action.');
  keys(value, ['action', 'token', 'code', 'profile', ...fields[value.action]], ['action', 'token', 'code', ...fields[value.action]]);
  if (typeof value.token !== 'string' || !HEX.test(value.token)) fail('Invalid private token.');
  if (value.action === 'create' ? value.code !== null : typeof value.code !== 'string' || !CODE.test(value.code)) fail('Invalid invitation code.');
  const body = {action: value.action, token: value.token, code: value.code};
  if ('profile' in value || ['create', 'pair'].includes(value.action)) body.profile = checkedProfile(value.profile);
  if (value.action === 'pair') {
    if (typeof value.peer !== 'string' || !CODE.test(value.peer)) fail('Invalid peer invitation.');
    body.peer = value.peer;
  }
  if (value.action === 'exchange') {
    if (!integer(value.received, 0, 512) || !Array.isArray(value.packets) || value.packets.length > 16) fail('Invalid native exchange.');
    body.received = value.received; body.packets = value.packets.map(checkedPacket);
  }
  return body;
}
function limit(env, name, ceiling) {
  const value = env[name] === undefined ? ceiling : Number(env[name]);
  if (!integer(value, 1, ceiling)) fail('Service limit configuration invalid.', 503);
  return value;
}
function randomCode() {
  const alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
  let code = '';
  while (code.length < 8) for (const byte of crypto.getRandomValues(new Uint8Array(16))) {
    if (byte < Math.floor(256 / alphabet.length) * alphabet.length) code += alphabet[byte % alphabet.length];
    if (code.length === 8) break;
  }
  return code;
}
export class PairingState {
  constructor(storage, env = {}) {
    this.storage = storage; this.sql = storage.sql;
    this.limits = {
      requestMinute: limit(env, 'REQUESTS_PER_IP_MINUTE', 600),
      requestGlobal: limit(env, 'REQUESTS_GLOBAL_DAY', 8000),
      createHour: limit(env, 'CREATE_PER_IP_HOUR', 10),
      createDay: limit(env, 'CREATE_PER_IP_DAY', 20),
      createGlobal: limit(env, 'CREATE_GLOBAL_DAY', 500),
    };
    this.sql.exec(`CREATE TABLE IF NOT EXISTS pairing_records (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS pairing_expiry ON pairing_records(expires);
      CREATE TABLE IF NOT EXISTS pairing_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);`);
    storage.transactionSync(() => {
      this.sql.exec('INSERT OR IGNORE INTO pairing_meta (key,value) VALUES (?,?)', 'ip-salt', crypto.randomUUID());
      this.ipSalt = this.sql.exec('SELECT value FROM pairing_meta WHERE key = ?', 'ip-salt').toArray()[0].value;
    });
  }
  get(key) {
    const row = this.sql.exec('SELECT value FROM pairing_records WHERE key = ?', key).toArray()[0];
    return row ? JSON.parse(row.value) : null;
  }
  put(key, value, expires) {
    this.sql.exec('INSERT INTO pairing_records (key,value,expires) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,expires=excluded.expires', key, JSON.stringify(value), expires);
  }
  cleanup(now) {this.sql.exec('DELETE FROM pairing_records WHERE expires <= ?', now);}
  nextExpiry() {return this.sql.exec('SELECT MIN(expires) AS expires FROM pairing_records').toArray()[0]?.expires ?? null;}
  quota(key, max, expires) {
    const used = this.get(`quota:${key}`) || 0;
    if (used >= max) fail('Service quota reached. Please try later.', 429);
    this.put(`quota:${key}`, used + 1, expires);
  }
  chargeRequest(ipHash, now) {
    // Count invalid and IP-throttled posts against the global ceiling too.
    this.storage.transactionSync(() => {
      this.cleanup(now);
      this.quota(`request-global:${Math.floor(now / 86400000)}`, this.limits.requestGlobal, (Math.floor(now / 86400000) + 1) * 86400000);
    });
    this.storage.transactionSync(() => this.quota(`request:${ipHash}:${Math.floor(now / 60000)}`, this.limits.requestMinute, (Math.floor(now / 60000) + 1) * 60000));
  }
  resolve(code, now) {
    let room = this.get(`room:${code}`);
    if (!room || room.expires <= now) fail('Invitation expired or unavailable.', 404);
    if (room.alias) {
      const target = this.get(`room:${room.alias}`);
      if (!target || target.expires <= now || target.id !== room.targetId || target.alias) fail('Invitation expired or unavailable.', 404);
      room = target;
    }
    return room;
  }
  authenticate(code, tokenHash, now) {
    const room = this.resolve(code, now);
    const slot = room.members.findIndex(member => member.hash === tokenHash);
    if (slot < 0) fail('This device does not own the invitation.', 403);
    return {room, slot};
  }
  touch(room, slot, now) {
    if (!room.closed && room.members.length === 2 && room.members.some(member => now - member.seen > PEER_TIMEOUT)) room.closed = true;
    room.members[slot].seen = now;
    this.put(`room:${room.code}`, room, room.expires);
  }
  packetKey(room, slot, seq) {return `packet:${room.id}:${slot}:${String(seq).padStart(3, '0')}`;}
  view(room, slot) {
    const connected = room.members.length === 2 && !room.closed;
    const packets = connected ? this.sql.exec('SELECT value FROM pairing_records WHERE key > ? AND key < ? ORDER BY key LIMIT 16',
      this.packetKey(room, 1 - slot, room.members[slot].received), this.packetKey(room, 1 - slot, 999)).toArray().map(row => JSON.parse(row.value)) : [];
    return {code: room.code, slot, expires: room.expires, connected, closed: room.closed,
      peerProfile: room.members[1 - slot]?.profile || null, accepted: room.members[1 - slot]?.received || 0, packets};
  }
  apply(body, {tokenHash, ipHash, now}) {
    return this.storage.transactionSync(() => {
      this.cleanup(now);
      const day = Math.floor(now / 86400000), dayEnd = (day + 1) * 86400000;
      if (body.action === 'create') {
        const existing = this.get(`token:${tokenHash}`);
        if (existing) {
          const {room, slot} = this.authenticate(existing.code, tokenHash, now);
          if (room.id !== existing.id || JSON.stringify(room.members[slot].profile) !== JSON.stringify(body.profile)) fail('Token is bound to a different profile.', 409);
          this.touch(room, slot, now); return this.view(room, slot);
        }
        this.quota(`create-hour:${ipHash}:${Math.floor(now / 3600000)}`, this.limits.createHour, (Math.floor(now / 3600000) + 1) * 3600000);
        this.quota(`create-day:${ipHash}:${day}`, this.limits.createDay, dayEnd);
        this.quota(`create-global:${day}`, this.limits.createGlobal, dayEnd);
        let code;
        for (let i = 0; i < 16; i++) {const candidate = randomCode(); if (!this.get(`room:${candidate}`)) {code = candidate; break;}}
        if (!code) fail('Invitation allocation unavailable.', 503);
        const room = {code, id: crypto.randomUUID(), expires: now + SESSION_TTL, closed: false,
          members: [{hash: tokenHash, profile: body.profile, sent: 0, received: 0, seen: now}]};
        this.put(`room:${code}`, room, room.expires); this.put(`token:${tokenHash}`, {code, id: room.id}, room.expires);
        return this.view(room, 0);
      }
      const {room, slot} = this.authenticate(body.code, tokenHash, now);
      if (body.profile && JSON.stringify(room.members[slot].profile) !== JSON.stringify(body.profile)) fail('Token is bound to a different profile.', 409);
      this.touch(room, slot, now);
      if (body.action === 'pair') {
        if (room.closed) fail('Pairing has ended.', 409);
        const peer = this.resolve(body.peer, now);
        if (peer.closed || peer.members[0].profile.transport !== body.profile.transport) fail('Peer pairing is incompatible or closed.', 409);
        if (room.code === peer.code) {
          if (room.members.length !== 2) fail('Scan another phone invitation.', 409);
          return this.view(room, slot);
        }
        if (room.members.length !== 1 || peer.members.length !== 1) fail('Pairing already contains two phones.', 409);
        if (room.members[0].hash === peer.members[0].hash) fail('Scan another phone invitation.', 409);
        const [canonical, alias] = room.code < peer.code ? [room, peer] : [peer, room];
        canonical.expires = Math.min(canonical.expires, alias.expires); canonical.members.push(alias.members[0]);
        for (const member of canonical.members) member.seen = now;
        this.put(`room:${canonical.code}`, canonical, canonical.expires);
        this.put(`room:${alias.code}`, {alias: canonical.code, targetId: canonical.id, expires: canonical.expires}, canonical.expires);
        for (const member of canonical.members) this.put(`token:${member.hash}`, {code: canonical.code, id: canonical.id}, canonical.expires);
        return this.view(canonical, canonical.members.findIndex(member => member.hash === tokenHash));
      }
      if (body.action === 'leave') {room.closed = true; this.put(`room:${room.code}`, room, room.expires); return this.view(room, slot);}
      if (room.closed) return this.view(room, slot);
      const member = room.members[slot], peer = room.members[1 - slot];
      if (!peer) {
        if (body.packets.length || body.received) fail('Pairing is not active.', 409);
        return this.view(room, slot);
      }
      if (body.received < member.received || body.received > peer.sent) fail('Invalid received cursor.', 409);
      for (let i = 0; i < body.packets.length; i++) {
        const packet = body.packets[i];
        if (i > 0 && packet.seq !== body.packets[i - 1].seq + 1) fail('Packet sequence gap.', 409);
        if (packet.seq <= member.sent) {
          if (JSON.stringify(this.get(this.packetKey(room, slot, packet.seq))) !== JSON.stringify(packet)) fail('Packet retry changed content.', 409);
        } else {
          if (packet.seq !== member.sent + 1) fail('Packet sequence gap.', 409);
          this.put(this.packetKey(room, slot, packet.seq), packet, room.expires); member.sent++;
        }
      }
      member.received = body.received;
      this.put(`room:${room.code}`, room, room.expires);
      return this.view(room, slot);
    });
  }
}
