#!/usr/bin/env node
// time-asks.mjs — tap every prepared question once, one at a time, on the model that is answering now, so the
// traffic lights on the ask buttons start from real numbers. The wall does the timing itself (ask: true); this only asks.
//   node deploy/linode/time-asks.mjs https://demo.instockornot.club GATE-KEY [rounds]
// Same session shape the wall's driver opens (default persona, greedy, 4k window). No key = a wall without a gate.
import { createRequire } from 'node:module';
const L = createRequire(import.meta.url)('../../static/peek/lib.js');

const [base, key, rounds = '1'] = process.argv.slice(2);
if (!base) { console.error('usage: time-asks.mjs BASE_URL [GATE-KEY] [rounds]'); process.exit(2); }
const url = p => base.replace(/\/$/, '') + p;
let cookie = '';

async function call(path, body) {
  const r = await fetch(url(path), { method: body === undefined ? 'GET' : 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, cookie ? { Cookie: cookie } : {}),
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${(await r.text()).slice(0, 200)}`);
  return r;
}

if (key) {
  const r = await call('/api/gate', { key });
  cookie = (r.headers.getSetCookie() || []).map(c => c.split(';')[0]).join('; ');
  if (!cookie) throw new Error('the gate gave no cookie');
}
const health = await (await call('/api/health')).json();
console.log(`model: ${health.model}   vllm: ${health.vllm}`);
const asks = L.asksFor(false);
for (let round = 1; round <= Number(rounds); round++) {
  for (const text of asks) {
    const session = Object.assign({ mode: 'compact', board: true, peek: true, tools: false, window: 4096 }, L.personaSessionFields(null));
    const sid = (await (await call('/api/session', session)).json()).session_id;
    const t0 = Date.now();
    try {
      const t = (await (await call('/api/turn', { session_id: sid, text, ask: true })).json()).turn;
      console.log(`${((Date.now() - t0) / 1000).toFixed(1).padStart(6)} s  ${String((t.tokens || []).length).padStart(5)} tokens${t.cut ? ' (cut)' : ''}  ${text.slice(0, 70)}`);
    } catch (e) { console.log(`   FAILED  ${text.slice(0, 60)}  ${e.message}`); }
  }
}
const lights = (await (await call('/api/timings')).json()).timings;
console.log('\nthe lights now:');
for (const text of asks) {
  const a = L.askLight(lights, text);
  console.log(`  ${(a.light || '-').padEnd(7)} ${a.label.padEnd(14)} ${text.slice(0, 70)}`);
}
