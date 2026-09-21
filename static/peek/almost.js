// "What it almost said": the ranked guesses behind the piece in focus.
peekPanels.almost = (function () {
  let el, toks = [], sawForeign = false;
  const vis = t => t.replace(/ /g, '␣').replace(/\n/g, '⏎');                       // make spaces and newlines visible
  const foreign = t => /[^\u0000-\u024F\u2000-\u206F]/.test(t);     // outside Latin + punctuation
  return {
    mount(root) { el = root; el.innerHTML = '<div class="cap">what it almost said</div><div id="rows" class="dim">tap a piece of the answer</div><div id="note" class="dim" style="font-size:.75em"></div>'; },
    onTurn(msg) { toks = (msg && msg.turn && msg.turn.tokens) || []; el.querySelector('#rows').innerHTML = '<span class="dim">…</span>'; },
    onSelect(i) {
      const t = toks[i]; if (!t) return;
      el.querySelector('#rows').innerHTML = t.alts.map(a =>
        `<div class="bar-row${a.t === t.t ? ' chosen' : ''}"><span class="w"></span><span class="b"><i style="width:${Math.max(1, a.p * 100)}%"></i></span><span>${peekLib.pct(a.p)}</span></div>`).join('');
      el.querySelectorAll('.bar-row .w').forEach((w, k) => { w.textContent = vis(t.alts[k].t); });
      if (!sawForeign && t.alts.some(a => foreign(a.t))) {
        sawForeign = true;
        el.querySelector('#note').textContent = 'Guesses in other languages are real: the model learned many languages at once, and they all compete for every piece.';
      }
    },
  };
})();
