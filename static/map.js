// The map: what the conversation is holding, drawn as a concept graph. d3-force on a 2D canvas.
// Nodes = concepts the model extracted. Size = mentions. Washed-out = survived only on paper (generation).
(() => {
  const NOW = () => performance.now();
  let canvas, ctx, sim, nodes = [], links = [], byId = new Map(), W = 0, H = 0, collapse = null;
  const css = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();
  const R = m => 9 + 5 * Math.sqrt(m);
  function resize() {
    if (!canvas) return;
    const b = canvas.getBoundingClientRect(); if (!b.width) return;
    const dpr = devicePixelRatio || 1;
    canvas.width = b.width * dpr; canvas.height = b.height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    W = b.width; H = b.height;
    if (sim) sim.force('center', d3.forceCenter(W / 2, H / 2)).alpha(0.3).restart();
  }
  function init(el) {
    canvas = el; ctx = el.getContext('2d'); resize(); addEventListener('resize', resize);
    sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(l => 150 - 12 * Math.min(5, l.w)).strength(l => 0.12 + 0.08 * Math.min(5, l.w)))
      .force('charge', d3.forceManyBody().strength(-700).distanceMax(600))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(d => R(d.m) + 34))
      .alphaDecay(0.025).velocityDecay(0.35);
    requestAnimationFrame(loop);
  }
  const add = (id, m, gen, x, y) => {
    if (byId.has(id)) return byId.get(id);
    const n = { id, m: m || 1, gen: gen || 0, born: NOW(), x: x ?? W / 2 + (Math.random() - .5) * 200, y: y ?? H / 2 + (Math.random() - .5) * 200 };
    nodes.push(n); byId.set(id, n); return n;
  };
  const link = (a, b, w) => {
    const s = byId.get(a), t = byId.get(b); if (!s || !t) return;
    const e = links.find(l => (l.source.id === a && l.target.id === b) || (l.source.id === b && l.target.id === a));
    if (e) e.w = w; else links.push({ source: s, target: t, w });
  };
  function restart() { if (!sim) return; sim.nodes(nodes); sim.force('link').links(links); sim.alpha(0.7).restart(); }
  function seed(g) {
    nodes.length = 0; links = []; byId = new Map(); collapse = null;
    for (const n of (g && g.nodes) || []) add(n.label, n.mentions, n.generation);
    for (const [a, b, w] of (g && g.edges) || []) link(a, b, w);
    restart();
  }
  function applyDelta(d) {
    if (!d) return;
    for (const id of d.added || []) add(id, 1, 0);
    for (const id of d.bumped || []) { const n = byId.get(id); if (n) { n.m++; n.gen = 0; n.born = NOW(); } }
    for (const [a, b, w] of d.edges || []) link(a, b, w);
    if (d.survive) applySurvive(d.survive);
    restart();
  }
  function applySurvive(s) {
    if (!s) return;
    for (const [id, gen] of s.kept || []) { const n = byId.get(id); if (n) { n.gen = gen; n.pulse = NOW(); } }
    for (const [id, into] of s.absorbed || []) {
      const n = byId.get(id); if (!n) continue;
      n.fading = NOW(); n.target = (into && byId.get(into)) || null; n.tx = W / 2; n.ty = H / 2;
      byId.delete(id); links = links.filter(l => l.source.id !== id && l.target.id !== id);
    }
    restart();
  }
  function handoff(seedGraph) {
    collapse = { t0: NOW(), seed: seedGraph || { nodes: [], edges: [] } };
    links = []; for (const n of nodes) { n.fading = NOW(); n.target = null; n.tx = W / 2; n.ty = H / 2; }
    byId = new Map(); restart();
  }
  function clear() { nodes.length = 0; links = []; byId = new Map(); collapse = null; restart(); }
  function draw() {
    if (!W) resize();
    const t = NOW(); ctx.clearRect(0, 0, W, H);
    const bone = css('--bone'), moss = css('--moss'), dim = css('--dim'), ice = css('--ice'), amber = css('--amber');
    ctx.lineCap = 'round';
    for (const l of links) {
      ctx.strokeStyle = dim; ctx.globalAlpha = 0.4; ctx.lineWidth = 1 + 1.2 * Math.min(6, l.w);
      ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const r = R(n.m), age = t - n.born;
      if (!n.fading) { n.x = Math.max(r + 24, Math.min(W - r - 24, n.x)); n.y = Math.max(r + 24, Math.min(H - r - 40, n.y)); }   // stay inside the frame
      if (n.fading) {                              // absorbed: drift into the survivor (or the centre) and fade over 1.2 s
        const k = Math.min(1, (t - n.fading) / 1200);
        const tx = n.target ? n.target.x : n.tx, ty = n.target ? n.target.y : n.ty;
        n.fx = n.x += (tx - n.x) * 0.1; n.fy = n.y += (ty - n.y) * 0.1;
        if (k >= 1) { nodes.splice(i, 1); if (n.target) n.target.pulse = t; continue; }
        ctx.globalAlpha = 0.9 * (1 - k); ctx.fillStyle = amber;
        ctx.beginPath(); ctx.arc(n.x, n.y, r * (1 - 0.5 * k), 0, 7); ctx.fill(); ctx.globalAlpha = 1; continue;
      }
      const alpha = Math.max(0.35, 1 - 0.25 * n.gen);
      if (age < 2000) {                            // new or re-mentioned: green ring expanding out
        ctx.globalAlpha = 1 - age / 2000; ctx.strokeStyle = moss; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 4 + 10 * (age / 2000), 0, 7); ctx.stroke();
      }
      if (n.pulse && t - n.pulse < 700) {          // survived / absorbed something: blue pulse
        ctx.globalAlpha = 1 - (t - n.pulse) / 700; ctx.strokeStyle = ice; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 2 + 12 * ((t - n.pulse) / 700), 0, 7); ctx.stroke();
      }
      ctx.globalAlpha = alpha; ctx.fillStyle = n.gen ? ice : bone;
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7); ctx.fill();
      if (r > 7 || nodes.length < 45) {
        ctx.fillStyle = bone; ctx.font = `${r > 16 ? 19 : 16}px "Helvetica Neue", system-ui, sans-serif`; ctx.textAlign = 'center';
        ctx.fillText(n.gen > 1 ? `${n.id} ·${n.gen}` : n.id, n.x, n.y + r + 19);
      }
      ctx.globalAlpha = 1;
    }
    if (collapse) {                                // handoff: 1.5 s of everything falling into one note, then the seed unfolds
      const k = (t - collapse.t0) / 1500;
      ctx.globalAlpha = Math.min(1, k); ctx.fillStyle = ice;
      ctx.beginPath(); ctx.arc(W / 2, H / 2, 14 + 8 * Math.min(1, k), 0, 7); ctx.fill();
      ctx.fillStyle = bone; ctx.font = '14px system-ui'; ctx.textAlign = 'center'; ctx.fillText('handoff note', W / 2, H / 2 + 38); ctx.globalAlpha = 1;
      if (k >= 1) {
        const s = collapse.seed; collapse = null; nodes.length = 0; byId = new Map(); links = [];
        for (const n of s.nodes || []) add(n.label, n.mentions, n.generation, W / 2 + (Math.random() - .5) * 20, H / 2 + (Math.random() - .5) * 20);
        for (const [a, b, w] of s.edges || []) link(a, b, w);
        restart();
      }
    }
    if (!nodes.length && !collapse) {
      ctx.fillStyle = dim; ctx.font = '16px system-ui'; ctx.textAlign = 'center';
      ctx.fillText('say “hi compact demo” and ask something — the map draws what the model is holding', W / 2, H / 2);
    }
  }
  function loop() { draw(); requestAnimationFrame(loop); }
  window.ctxMap = { init, seed, applyDelta, applySurvive, handoff, clear, resize };
})();
