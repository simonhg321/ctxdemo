// "The answer": revealed piece by piece at the speed it was really generated, coloured by how sure the model was.
peekPanels.answer = (function () {
  let el, timer = null, toks = [];
  function paint(i) {
    el.querySelectorAll('.piece').forEach(s => s.classList.toggle('focus', +s.dataset.i === i));
  }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">the answer · <span style="color:var(--moss)">sure</span> · <span style="color:var(--amber)">unsure</span> · <span style="color:var(--red)">coin-flip</span></div><div id="out" class="dim">…</div>';
      el.addEventListener('click', e => {
        const s = e.target.closest('.piece'); if (!s) return;
        window.peekStopCycle && window.peekStopCycle();            // a person took over: stop the automatic tour
        const alone = new URLSearchParams(location.search).get('replay') === '1';   // self-replay: no bus joined
        if (alone) paint(+s.dataset.i); else peekBus.send('select', { index: +s.dataset.i });
      });
    },
    onTurn(msg) {
      clearInterval(timer);
      const out = el.querySelector('#out'), t = msg && msg.turn;
      out.className = ''; out.innerHTML = '';
      if (!t) { out.className = 'dim'; out.textContent = '…'; return; }
      toks = t.tokens || [];
      if (!toks.length) { out.textContent = t.answer || t.event_text || ''; return; }       // non-peek turn or over-limit: plain text
      let i = 0;
      const ring = new Set(peekLib.hesitations(toks, 3));
      timer = setInterval(() => {
        if (i >= toks.length) {
          clearInterval(timer); out.querySelectorAll('.piece').forEach(s => ring.has(+s.dataset.i) && s.classList.add('ring'));
          if (t.cut) { const c = document.createElement('span'); c.className = 'cut'; c.textContent = ` ⏹ cut off here — the wall allows ${toks.length} pieces per answer; the model was not done`; out.appendChild(c); }
          return;
        }
        const s = document.createElement('span');
        s.className = 'piece ' + peekLib.tone(toks[i].p); s.dataset.i = i; s.textContent = toks[i].t;
        out.appendChild(s); i++;
      }, peekLib.revealDelay(t.seconds || 2, toks.length));
    },
    onSelect(i) { paint(i); },
  };
})();
