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
  // Personas get a longer leash (1000 pieces vs the wall's 400): "show your steps" and custom prompts ask for long answers.
  const personaSessionFields = persona => (!persona ? {} : Object.assign({ max_tokens: 1000 }, persona.id === 'custom' ? { system: persona.prompt } : { persona: persona.id }));
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
  const api = { tone, pct, isBlank, hesitations, stats, revealDelay, personaModel, personaSessionFields, explainParse, explainInline };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.peekLib = api;
})(typeof window !== 'undefined' ? window : globalThis);
