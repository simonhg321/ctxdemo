import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const L = createRequire(import.meta.url)('./lib.js');

const T = (t, p, runner) => ({ t, p, alts: runner ? [{ t, p }, { t: runner, p: 1 - p }] : [{ t, p }] });

test('tone thresholds', () => {
  assert.equal(L.tone(0.9), 'sure'); assert.equal(L.tone(0.89), 'unsure');
  assert.equal(L.tone(0.5), 'unsure'); assert.equal(L.tone(0.49), 'flip');
});
test('pct', () => { assert.equal(L.pct(0.7197), '72%'); assert.equal(L.pct(0.0004), '<1%'); assert.equal(L.pct(1), '100%'); });
test('hesitations: lowest first, skips blank pieces', () => {
  const toks = [T('A', 0.99), T(' ', 0.1), T('B', 0.4, 'C'), T('D', 0.6, 'E'), T('\n', 0.2), T('F', 0.95)];
  assert.deepEqual(L.hesitations(toks, 2), [2, 3]);
  assert.deepEqual(L.hesitations([], 3), []);
  assert.deepEqual(L.hesitations(toks), [2, 3]);
  assert.deepEqual(L.hesitations([T('A', 0.99), T('B', 0.95)]), []);
});
test('stats', () => {
  const s = L.stats([T('A', 0.99), T('B', 0.4, 'C'), T('D', 0.95)]);
  assert.equal(s.sure_pct, 67); assert.deepEqual(s.worst, { i: 1, chosen: 'B', runner: 'C' });
  assert.deepEqual(L.stats([]), { sure_pct: 0, worst: null });
});
test('revealDelay: real pace, capped at 8 s total, floor 15 ms', () => {
  assert.equal(L.revealDelay(2, 40), 50); assert.equal(L.revealDelay(30, 100), 80); assert.equal(L.revealDelay(0.01, 100), 15);
});
test('personaModel: marks the active persona, custom handled elsewhere', () => {
  const personas = [{ id: 'wall', title: 'On the wall', blurb: 'b1' }, { id: 'pirate', title: 'Pirate', blurb: 'b2' }];
  assert.deepEqual(L.personaModel(personas, 'pirate'), [
    { id: 'wall', title: 'On the wall', blurb: 'b1', active: false },
    { id: 'pirate', title: 'Pirate', blurb: 'b2', active: true },
  ]);
  assert.deepEqual(L.personaModel(personas, null).map(b => b.active), [false, false]);
  assert.deepEqual(L.personaModel(personas, 'custom').map(b => b.active), [false, false]);
  assert.deepEqual(L.personaModel(undefined, 'x'), []);
});
test('personaSessionFields: persona id, or custom free text', () => {
  assert.deepEqual(L.personaSessionFields(null), {});
  assert.deepEqual(L.personaSessionFields({ id: 'pirate', prompt: 'Arr' }), { persona: 'pirate' });
  assert.deepEqual(L.personaSessionFields({ id: 'custom', prompt: 'be nice' }), { system: 'be nice' });
});
