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
  const api = { tone, pct, isBlank, hesitations, stats, revealDelay };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.peekLib = api;
})(typeof window !== 'undefined' ? window : globalThis);
