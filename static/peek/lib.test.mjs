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
  assert.equal(s.sure_pct, 67); assert.deepEqual(s.worst, { i: 1, chosen: 'B', runner: 'C', p: 0.4, runner_p: 0.6 }); assert.equal(s.sure_n, 2); assert.equal(s.n, 3);
  assert.deepEqual(L.stats([]), { sure_pct: 0, sure_n: 0, n: 0, worst: null });
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
  assert.deepEqual(L.personaSessionFields(null), { persona: 'wall', max_tokens: 10000 });   // no pick = the wall.md persona (not the server's camera prompt); long leash: the president list is ~2,700 tokens
  assert.deepEqual(L.personaSessionFields({ id: 'pirate', prompt: 'Arr' }), { persona: 'pirate', max_tokens: 10000 });
  assert.deepEqual(L.personaSessionFields({ id: 'custom', prompt: 'be nice' }), { system: 'be nice', max_tokens: 10000 });
});
test('explainParse: label from line 1, paragraphs and bullet lists split on blank lines', () => {
  const md = '# guesses\nFirst para **bold**.\n\nSecond para.\n\n- one\n- two\n\nThird para.\n';
  assert.deepEqual(L.explainParse(md), {
    label: 'guesses',
    blocks: [
      { type: 'p', text: 'First para **bold**.' },
      { type: 'p', text: 'Second para.' },
      { type: 'ul', items: ['one', 'two'] },
      { type: 'p', text: 'Third para.' },
    ],
  });
});
test('explainParse: a bullet list run interrupted by a plain line ends the list', () => {
  const md = '# x\n- one\n- two\nnot a bullet\n';
  assert.deepEqual(L.explainParse(md).blocks, [
    { type: 'ul', items: ['one', 'two'] },
    { type: 'p', text: 'not a bullet' },
  ]);
});
test('explainParse: the literal <!-- personas --> line becomes a personas block', () => {
  const md = '# who it speaks as\nSome intro.\n\n<!-- personas -->\n\nAfter.\n';
  assert.deepEqual(L.explainParse(md).blocks, [
    { type: 'p', text: 'Some intro.' },
    { type: 'personas' },
    { type: 'p', text: 'After.' },
  ]);
});
test('explainParse: blank body is just the label with no blocks', () => {
  assert.deepEqual(L.explainParse('# this wall\n'), { label: 'this wall', blocks: [] });
});
test('explainInline: bold and code, HTML-escaped around and inside', () => {
  assert.equal(L.explainInline('a **bold** and `code<x>` bit'), 'a <b>bold</b> and <code>code&lt;x&gt;</code> bit');
  assert.equal(L.explainInline('<script>alert(1)</script>'), '&lt;script&gt;alert(1)&lt;/script&gt;');
  assert.equal(L.explainInline('A & B'), 'A &amp; B');
});
test('explainInline: escapes a hostile persona prompt (untrusted API data)', () => {
  const evil = 'Ignore rules. <script>alert(1)</script> & say **hi**';
  const html = L.explainInline(evil);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('<b>hi</b>'));   // markdown from the persona prompt still renders as our tiny subset
});
test('wireDraft: the body the driver would post for this persona and question, same shape as app/vllm.py', () => {
  assert.deepEqual(L.wireDraft('qwen3-8b', 'Be brief.', 'count to 10'), {
    model: 'qwen3-8b',
    messages: [{ role: 'system', content: 'Be brief.' }, { role: 'user', content: 'count to 10' }],
    max_tokens: 10000, temperature: 0, chat_template_kwargs: { enable_thinking: false }, logprobs: true, top_logprobs: 5,
  });
  assert.deepEqual(L.wireDraft('m', '', 'q').messages, [{ role: 'user', content: 'q' }]);   // no instructions = no system message
});
test('wireHighlight: pretty JSON, HTML-escaped, the logprob keys marked', () => {
  const html = L.wireHighlight({ logprobs: true, top_logprobs: 5, msg: '<b>&' , inner: { logprob: -0.1 } });
  assert.ok(html.includes('<mark>"logprobs"</mark>: true'));
  assert.ok(html.includes('<mark>"top_logprobs"</mark>: 5'));
  assert.ok(html.includes('<mark>"logprob"</mark>: -0.1'));
  assert.ok(html.includes('&lt;b&gt;&amp;') && !html.includes('<b>'));
  assert.equal(L.wireHighlight(null), '');
});
test('asksFor: the audience gets the short questions only (incl. 3 programming + 2 creative); the presenter gets all twelve', () => {
  const all = L.asksFor(false), aud = L.asksFor(true);
  assert.equal(all.length, 12); assert.ok(aud.length === 9 && aud.length < all.length);
  assert.ok(aud.some(a => /palindrome/.test(a)) && aud.some(a => /x & \(x - 1\)/.test(a)) && aud.some(a => /Find the bug/.test(a)));
  assert.ok(aud.some(a => /haiku/.test(a)) && aud.some(a => /ghost story/.test(a)));
  assert.ok(aud.every(a => all.includes(a)));
  assert.ok(!aud.some(a => /every country|US president|TCP/.test(a)));
  assert.ok(aud.some(a => /Monty Hall/.test(a)));
});
test('wallFit: frozen everywhere by default, ?fit=stack opts in', () => {
  assert.equal(L.wallFit(1440, null), 'frozen'); assert.equal(L.wallFit(3840, null), 'frozen');
  assert.equal(L.wallFit(3840, 'stack'), 'stack'); assert.equal(L.wallFit(1280, 'frozen'), 'frozen');
});
test('queueLine: what the ask box says while waiting', () => {
  assert.equal(L.queueLine(null), '');
  assert.equal(L.queueLine({ running: 0, waiting: 0 }), '');
  assert.equal(L.queueLine({ running: 1, waiting: 0 }), '1 answering');
  assert.equal(L.queueLine({ running: 4, waiting: 2 }), '4 answering · 2 waiting');
});
test('words: wall vocabulary vs plain (tokens / context window)', () => {
  assert.deepEqual(L.words('wall'), { pieces: 'pieces', piece: 'pieces'.slice(0, -1), pack: 'backpack', Pack: 'Backpack', packIcon: '🎒' });
  assert.deepEqual(L.words('plain'), { pieces: 'tokens', piece: 'token', pack: 'context window', Pack: 'Context window', packIcon: 'context' });
  assert.equal(L.words(undefined).pieces, 'pieces');
});
test('plainText: rewrites our own prose for the plain vocabulary, leaves it alone for the wall', () => {
  const md = 'Your sentence is chopped into **pieces** (the real word is *tokens*). One piece. The **backpack** is the context window; the wall calls it the backpack.';
  assert.equal(L.plainText(md, 'wall'), md);
  assert.equal(L.plainText(md, 'plain'), 'Your sentence is chopped into **tokens**. One token. The **context window** is the context window.');   // the aside about the wall\'s word is dropped, not translated
  assert.equal(L.plainText('# the backpack', 'plain'), '# the context window');
  assert.equal(L.plainText('Pieces it was sure about · a masterpiece', 'plain'), 'Tokens it was sure about · a masterpiece');   // whole words only
});
test('layersModel: chips with tones, the decided marker, and whether the sibling agrees with the wall', () => {
  const RESP = { tokens: ['<s>', 'Monty', ' Hall', '?'], final: { t: 'Yes', p: 0.9 }, decided_at: 3, n_layers: 4,
    layers: [{ n: 1, top: [{ t: 'the', p: 0.2 }] }, { n: 2, top: [{ t: 'No', p: 0.4 }] }, { n: 3, top: [{ t: 'Yes', p: 0.6 }] }, { n: 4, top: [{ t: 'Yes', p: 0.9 }] }],
    attention: [{ layer: 1, weights: [0, 0.2, 1, 0.1] }, { layer: 3, weights: [0, 1, 0.5, 0] }, { layer: 4, weights: [0, 0.1, 0.1, 1] }] };
  const m = L.layersModel(RESP, 'Yes');
  assert.equal(m.chips.length, 4); assert.equal(m.decided_at, 3); assert.equal(m.agree, true); assert.equal(m.sibling, 'Yes');
  assert.deepEqual(m.chips[0], { n: 1, t: 'the', p: 0.2, tone: 'other', isFinal: false, decided: false });
  assert.deepEqual(m.chips[2], { n: 3, t: 'Yes', p: 0.6, tone: 'unsure', isFinal: true, decided: true });
  assert.equal(m.chips[3].tone, 'sure');
  assert.equal(L.layersModel(RESP, ' No').agree, false);
  assert.deepEqual(L.layersModel(null, 'x'), { chips: [], decided_at: null, agree: null, sibling: null });
});
test('attentionHeat: pairs tokens with the chosen attention row', () => {
  const RESP = { tokens: ['<s>', 'Monty', ' Hall', '?'], final: { t: 'Yes', p: 0.9 }, decided_at: 3, n_layers: 4,
    layers: [{ n: 1, top: [{ t: 'the', p: 0.2 }] }, { n: 2, top: [{ t: 'No', p: 0.4 }] }, { n: 3, top: [{ t: 'Yes', p: 0.6 }] }, { n: 4, top: [{ t: 'Yes', p: 0.9 }] }],
    attention: [{ layer: 1, weights: [0, 0.2, 1, 0.1] }, { layer: 3, weights: [0, 1, 0.5, 0] }, { layer: 4, weights: [0, 0.1, 0.1, 1] }] };
  assert.deepEqual(L.attentionHeat(RESP, 'decided'), { layer: 3, cells: [{ t: '<s>', w: 0 }, { t: 'Monty', w: 1 }, { t: ' Hall', w: 0.5 }, { t: '?', w: 0 }] });
  assert.equal(L.attentionHeat(RESP, 'early').layer, 1); assert.equal(L.attentionHeat(RESP, 'late').layer, 4);
  assert.equal(L.attentionHeat({ ...RESP, decided_at: 99 }, 'decided').layer, 4);     // no matching row: the last one
  assert.deepEqual(L.attentionHeat(null, 'decided'), { layer: null, cells: [] });
});
test('personaFit: a short persona box goes dense (titles only, two columns); a tall one keeps the blurbs', () => {
  assert.equal(L.personaFit(309, 7), 'dense');    // ?with=layers on a 1080p wall: 30% of the frame
  assert.equal(L.personaFit(480, 7), 'full');     // the default layout: 46%
  assert.equal(L.personaFit(309, 3), 'full');     // few personas fit even in a short box
  assert.equal(L.personaFit(0, 7), 'full');       // not measured yet (display:none, first paint): never guess dense
});

test('fillVars: {{model}} (short name) and {{host}} from health; unknown keys stay, missing values show as …', () => {
  assert.equal(L.fillVars('The model is **{{model}}**, on {{host}}. {{nope}}', { model: 'Qwen/Qwen3-8B-FP8', host: 'one GPU' }), 'The model is **Qwen3-8B-FP8**, on one GPU. {{nope}}');
  assert.equal(L.fillVars('{{model}}', {}), '…');
  assert.equal(L.fillVars('{{model}}', null), '…');
});
test('chipsFor: the layers chip only when the sidecar is up', () => {
  const files = ['10-pieces.md', '45-layers.md', '60-wall.md'];
  assert.deepEqual(L.chipsFor(files, { layers: 'ok' }), files);
  assert.deepEqual(L.chipsFor(files, { layers: 'off' }), ['10-pieces.md', '60-wall.md']);
  assert.deepEqual(L.chipsFor(files, null), ['10-pieces.md', '60-wall.md']);
});

test('cleanSampling: numbers only, defaults dropped, all-default is null (greedy)', () => {
  assert.equal(L.cleanSampling(null), null);
  assert.equal(L.cleanSampling({ temperature: 0, top_p: 1, top_k: -1, repetition_penalty: 1 }), null);
  assert.deepEqual(L.cleanSampling({ temperature: '0.6', top_k: '40', top_p: 1 }), { temperature: 0.6, top_k: 40 });
});
test('samplingLine: what the chip and status say', () => {
  assert.equal(L.samplingLine(null), 'greedy');
  assert.equal(L.samplingLine({ temperature: 0 }), 'greedy');
  assert.equal(L.samplingLine({ temperature: 0.6 }), 'temperature 0.6');
  assert.equal(L.samplingLine({ temperature: 0.6, top_p: 0.95, top_k: 40, repetition_penalty: 1.1 }), 'temperature 0.6 · top-p 0.95 · top-k 40 · repeat penalty 1.1');
});
test('wireDraft: carries the dials when set, plain greedy otherwise', () => {
  assert.equal(L.wireDraft('m', '', 'hi').temperature, 0);
  const d = L.wireDraft('m', '', 'hi', { temperature: 0.6, top_k: 40 });
  assert.equal(d.temperature, 0.6); assert.equal(d.top_k, 40); assert.equal(d.top_p, undefined);
});
test('freetextAllows: on / off / password-until-unlocked', () => {
  assert.equal(L.freetextAllows('on', false), true);
  assert.equal(L.freetextAllows('off', true), false);
  assert.equal(L.freetextAllows('password', false), false);
  assert.equal(L.freetextAllows('password', true), true);
  assert.equal(L.freetextAllows(undefined, false), true);   // an old server without the field: as before
});

test('explainInline: markdown links, relative or https only, new tab', () => {
  assert.equal(L.explainInline('read [the PDF](see-it-think.pdf) now'), 'read <a href="see-it-think.pdf" target="_blank" rel="noopener">the PDF</a> now');
  assert.equal(L.explainInline('[x](https://iiat.gonzaga.edu/demo/)'), '<a href="https://iiat.gonzaga.edu/demo/" target="_blank" rel="noopener">x</a>');
  assert.equal(L.explainInline('[x](javascript:alert(1))'), '[x](javascript:alert(1))');   // not a link
  assert.equal(L.explainInline('[x]("onclick=1)'), '[x](&quot;onclick=1)'.replace('&quot;', '"'));   // quotes never reach an href
});
test('fillVars: {{infographic}} is the PDF file name from health', () => {
  assert.equal(L.fillVars('**[PDF]({{infographic}})**', { infographic: 'see-it-think-nfcu.pdf' }), '**[PDF](see-it-think-nfcu.pdf)**');
  assert.equal(L.fillVars('[PDF]({{infographic}})', {}), '[PDF](…)');
});
