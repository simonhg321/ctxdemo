// Pure helpers for the act-6 panels. Loaded by <script> in the browser (window.peekLib) and by node for tests.
(function (root) {
  const tone = p => (p >= 0.9 ? 'sure' : p >= 0.5 ? 'unsure' : 'flip');
  const pct = p => (p > 0 && p < 0.005 ? '<1%' : Math.round(p * 100) + '%');
  const isBlank = t => !String(t || '').trim();
  function hesitations(tokens, k = 3) {
    return (tokens || []).map((t, i) => ({ i, p: t.p, t: t.t })).filter(x => !isBlank(x.t) && x.p < 0.9)
      .sort((a, b) => a.p - b.p || a.i - b.i).slice(0, k).map(x => x.i).sort((a, b) => a - b);
  }
  function stats(tokens) {
    const real = (tokens || []).map((t, i) => ({ ...t, i })).filter(t => !isBlank(t.t));
    if (!real.length) return { sure_pct: 0, worst: null };
    const w = real.reduce((a, b) => (b.p < a.p ? b : a));
    const runner = (w.alts || []).find(a => a.t !== w.t);
    return { sure_pct: Math.round(100 * real.filter(t => t.p >= 0.9).length / real.length),
             worst: { i: w.i, chosen: w.t, runner: runner ? runner.t : null } };
  }
  const revealDelay = (seconds, n) => Math.max(15, Math.round(Math.min(seconds, 8) * 1000 / Math.max(1, n)));
  // act 6, persona panel: the button model (custom is a fixed button the panel draws itself, never in this list).
  const personaModel = (personas, activeId) => (personas || []).map(p => ({ ...p, active: p.id === activeId }));
  // what to add to the /api/session body for the currently-picked persona: an id, or free text for "custom".
  // Personas get a long leash (10,000 pieces vs the wall's 400): "show your steps" and custom prompts ask for long answers.
  const personaSessionFields = persona => Object.assign({ max_tokens: 10000 }, !persona ? {} : persona.id === 'custom' ? { system: persona.prompt } : { persona: persona.id });
  // act 6, explain bar: parse our tiny markdown subset (paragraphs, `- ` lists, and the <!-- personas --> placeholder).
  function explainParse(mdText) {
    const lines = String(mdText || '').replace(/\r\n/g, '\n').split('\n');
    const label = (lines[0] || '').replace(/^#\s*/, '').trim();
    const blocks = [];
    let para = [], items = null;
    const flushPara = () => { if (para.length) { blocks.push({ type: 'p', text: para.join(' ').trim() }); para = []; } };
    const flushUl = () => { if (items) { blocks.push({ type: 'ul', items }); items = null; } };
    for (const raw of lines.slice(1)) {
      const line = raw.trim();
      if (!line) { flushPara(); flushUl(); continue; }
      if (line === '<!-- personas -->') { flushPara(); flushUl(); blocks.push({ type: 'personas' }); continue; }
      if (line.startsWith('- ')) { flushPara(); (items = items || []).push(line.slice(2).trim()); continue; }
      flushUl(); para.push(line);
    }
    flushPara(); flushUl();
    return { label, blocks };
  }
  // **bold** and `code`, everything else HTML-escaped — the card renders our files, but persona titles/prompts from
  // the API pass through here too, so escaping has to hold even when the text isn't ours.
  function explainInline(text) {
    const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return esc(String(text || ''))
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/`(.+?)`/g, '<code>$1</code>');
  }
  // act 6, wire panel: the body the driver would post for this persona + question — the same shape app/vllm.py builds
  // (peek session, persona leash 10,000). Shown before the first turn so the room can see the two flags without waiting.
  function wireDraft(model, systemPrompt, userText) {
    const messages = [];
    if (systemPrompt) messages.push({ role: 'system', content: systemPrompt });
    messages.push({ role: 'user', content: userText });
    return { model, messages, max_tokens: 10000, temperature: 0, chat_template_kwargs: { enable_thinking: false }, logprobs: true, top_logprobs: 5 };
  }
  // Pretty JSON as safe HTML with the probability keys wrapped in <mark> — the two we ask with, the two that answer.
  function wireHighlight(obj) {
    if (obj == null) return '';
    const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return esc(JSON.stringify(obj, null, 2)).replace(/"(logprobs|top_logprobs|logprob)":/g, '<mark>"$1"</mark>:');
  }
  // the "try asking" buttons. Long ones (~2–3k tokens) are for the presenter's wall only: on a shared GPU they jam the room.
  const ASKS_SHORT = ['Pick a number between 1 and 10', 'Divide by 3 in C using only shifts',
    'Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?', 'How many r\'s are in strawberry?'];
  const ASKS_LONG = ['List every country in the world with its capital',
    'Every US president in order, with years and one thing each is remembered for',
    'Explain how TCP delivers a file, step by step, from SYN to the last ACK'];
  const asksFor = audience => (audience ? ASKS_SHORT : ASKS_SHORT.concat(ASKS_LONG));
  // wall.html: the frozen %-boxes everywhere (Simon prefers them on the laptop too); ?fit=stack opts into the scrolling stack.
  const wallFit = (width, fit) => (fit === 'stack' ? 'stack' : 'frozen');
  // the ask box's waiting line, from /api/queue: '' when idle or unknown.
  const queueLine = q => (!q || (!q.running && !q.waiting) ? '' : `${q.running} answering` + (q.waiting ? ` · ${q.waiting} waiting` : ''));
  // the words on the wall: 'wall' = pieces / backpack (students), 'plain' = tokens / context window (an engineer audience).
  // CTXDEMO_VOCAB on the server -> /api/health.vocab -> panel.html calls setVocab before any panel mounts.
  let vocabMode = 'wall';
  const setVocab = mode => { vocabMode = mode === 'plain' ? 'plain' : 'wall'; };
  const words = mode => ((mode || vocabMode) === 'plain'
    ? { pieces: 'tokens', piece: 'token', pack: 'context window', Pack: 'Context window', packIcon: 'context' }
    : { pieces: 'pieces', piece: 'piece', pack: 'backpack', Pack: 'Backpack', packIcon: '\u{1F392}' });
  // our own prose (explain cards, captions) rewritten for the plain vocabulary; whole words only, never user text
  function plainText(text, mode) {
    if ((mode || vocabMode) !== 'plain') return String(text || '');
    return String(text || '')
      .replace(/ \(the real word is \*tokens\*\)/g, '')
      .replace(/\bPieces\b/g, 'Tokens').replace(/\bpieces\b/g, 'tokens').replace(/\bPiece\b/g, 'Token').replace(/\bpiece\b/g, 'token')
      .replace(/\bBackpack\b/g, 'Context window').replace(/\bbackpack\b/g, 'context window');
  }
  // piece 4, layers panel: one chip per layer from the sidecar's response; the final token's tone once a layer agrees with it.
  function layersModel(resp, wallToken) {
    if (!resp || !resp.layers) return { chips: [], decided_at: null, agree: null, sibling: null };
    const fin = resp.final ? resp.final.t : null;
    const chips = resp.layers.map(l => {
      const top = (l.top && l.top[0]) || { t: '', p: 0 };
      const isFinal = top.t === fin;
      return { n: l.n, t: top.t, p: top.p, tone: isFinal ? tone(top.p) : 'other', isFinal, decided: l.n === resp.decided_at };
    });
    const norm = s => String(s == null ? '' : s).trim();
    return { chips, decided_at: resp.decided_at ?? null, agree: fin == null || wallToken == null ? null : norm(fin) === norm(wallToken), sibling: fin };
  }
  // the "where it looked" strip: prompt tokens paired with one attention row (early / decided / late).
  function attentionHeat(resp, which) {
    if (!resp || !resp.attention || !resp.attention.length) return { layer: null, cells: [] };
    const rows = resp.attention;
    const row = which === 'early' ? rows[0] : which === 'late' ? rows[rows.length - 1]
      : (rows.find(r => r.layer === resp.decided_at) || rows[rows.length - 1]);
    return { layer: row.layer, cells: (resp.tokens || []).map((t, i) => ({ t, w: row.weights[i] ?? 0 })) };
  }
  const api = { setVocab, words, plainText, queueLine, asksFor, wallFit, tone, pct, isBlank, hesitations, stats, revealDelay, personaModel, personaSessionFields, explainParse, explainInline, wireDraft, wireHighlight, layersModel, attentionHeat };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.peekLib = api;
})(typeof window !== 'undefined' ? window : globalThis);
