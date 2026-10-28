// SPDX-License-Identifier: GPL-3.0-or-later
import {MAX_BODY, PairingState, ServiceError, validateBody} from './state.mjs';

const json = (body, status = 200, extra = {}) => new Response(JSON.stringify(body), {
  status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', ...extra},
});
const errorResponse = (error, extra = {}) => json({error: error instanceof ServiceError ? error.message : 'Link service unavailable.'},
  error instanceof ServiceError ? error.status : 503, extra);
const hash = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))), b => b.toString(16).padStart(2, '0')).join('');

async function boundedJson(stream) {
  if (!stream) throw new ServiceError('Missing JSON body.');
  const reader = stream.getReader(), chunks = [];
  let total = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY) {await reader.cancel(); throw new ServiceError('Body exceeds size limit.', 413);}
      chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const data = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {data.set(chunk, offset); offset += chunk.length;}
  try {return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(data));}
  catch {throw new ServiceError('Invalid JSON body.');}
}

export async function handleLink(request, state, env, {now = Date.now} = {}) {
  try {
    if (request.method !== 'POST') throw new ServiceError('POST required.');
    const current = now(), ip = request.headers.get('CF-Connecting-IP') || 'unavailable';
    const ipHash = await hash(`ip:${state.ipSalt}:${Math.floor(current / 86400000)}:${ip}`);
    state.chargeRequest(ipHash, current);
    if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('Content-Type') || '')) throw new ServiceError('JSON content type required.');
    if (Number(request.headers.get('Content-Length') || 0) > MAX_BODY) throw new ServiceError('Body exceeds size limit.', 413);
    const body = validateBody(await boundedJson(request.body));
    const tokenHash = await hash(`penc-link-v1:${body.token}`);
    return json(state.apply(body, {tokenHash, ipHash, now: now()}));
  } catch (error) {return errorResponse(error);}
}

export class PairingObject {
  constructor(ctx, env) {this.ctx = ctx; this.env = env; this.state = new PairingState(ctx.storage, env);}
  async fetch(request) {
    const response = await handleLink(request, this.state, this.env);
    await this.scheduleCleanup();
    return response;
  }
  async scheduleCleanup() {
    const expiry = this.state.nextExpiry();
    if (expiry !== null) {
      const existing = await this.ctx.storage.getAlarm();
      if (existing === null || existing > expiry) await this.ctx.storage.setAlarm(Math.max(Date.now() + 1000, expiry));
    }
  }
  async alarm() {
    this.ctx.storage.transactionSync(() => this.state.cleanup(Date.now()));
    await this.scheduleCleanup();
  }
}

export default {
  async fetch(request, env) {
    let cors = {};
    try {
      const url = new URL(request.url);
      if (url.pathname === '/health' && request.method === 'GET') return json({ok: true});
      if (url.pathname !== '/api/link' || url.search) return json({error: 'Not found.'}, 404);
      const origin = request.headers.get('Origin');
      const allowed = String(env.ALLOWED_ORIGINS || '').split(',').map(value => value.trim()).filter(Boolean);
      if (!origin || !allowed.includes(origin)) return json({error: 'Origin is not allowed.'}, 403);
      cors = {'Access-Control-Allow-Origin': origin, Vary: 'Origin'};
      if (request.method === 'OPTIONS') {
        const method = request.headers.get('Access-Control-Request-Method');
        const headers = (request.headers.get('Access-Control-Request-Headers') || '').toLowerCase().split(',').map(value => value.trim()).filter(Boolean);
        if (method !== 'POST' || headers.some(value => value !== 'content-type')) return json({error: 'Preflight is not allowed.'}, 403, cors);
        return new Response(null, {status: 204, headers: {...cors, 'Cache-Control': 'no-store', 'Access-Control-Allow-Methods': 'POST',
          'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '600'}});
      }
      if (request.method !== 'POST') return json({error: 'POST required.'}, 400, cors);
      if (!env.PAIRING) return json({error: 'Link service unavailable.'}, 503, cors);
      // One singleton serializes all request and creation quota accounting.
      const id = env.PAIRING.idFromName('penc-link-v1');
      const response = await env.PAIRING.get(id).fetch(request);
      const result = new Response(response.body, response);
      for (const [key, value] of Object.entries(cors)) result.headers.set(key, value);
      return result;
    } catch (error) {return errorResponse(error, cors);}
  },
};
