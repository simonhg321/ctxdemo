// Three numbers: how sure, the biggest hesitation, how full the backpack is.
peekPanels.tiles = (function () {
  let el;
  const vis = t => (t == null ? '—' : '“' + t.trim() + '”');
  function personaTile(title) {                    // a fourth tile, only once a persona has been picked (absent: no tile, layout unchanged)
    let t = el.querySelector('#persona-tile');
    if (!title) { if (t) t.remove(); return; }
    if (!t) {
      t = document.createElement('div'); t.className = 'tile'; t.id = 'persona-tile';
      t.innerHTML = '<div class="cap">speaking as</div><div class="big" id="persona-big"></div>';
      el.appendChild(t);
    }
    t.querySelector('#persona-big').textContent = title;
  }
  return {
    mount(root) {
      el = root;
      el.classList.add('row');
      el.innerHTML = ['sure', 'worst', 'pack'].map(k => `<div class="tile"><div class="cap" id="${k}-cap"></div><div class="big" id="${k}-big">—</div></div>`).join('');
      el.querySelector('#sure-cap').textContent = 'pieces it was sure about';
      el.querySelector('#worst-cap').textContent = 'biggest hesitation';
      el.querySelector('#pack-cap').textContent = 'backpack full';
      peekBus.on('persona', d => personaTile(d.title));   // driver re-sends this on hello, so a late-joining tiles panel lights up too
    },
    onTurn(msg) {
      const t = msg && msg.turn, st = msg && msg.state, s = peekLib.stats(t && t.tokens);
      el.querySelector('#sure-big').textContent = t && t.tokens && t.tokens.length ? s.sure_pct + '%' : '—';
      el.querySelector('#worst-big').textContent = s.worst ? `${vis(s.worst.chosen)} vs ${vis(s.worst.runner)}` : '—';
      el.querySelector('#pack-big').textContent = st && st.window_tokens ? Math.round(100 * st.next_would_send / st.window_tokens) + '%' : '—';
    },
  };
})();
