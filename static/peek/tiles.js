// Three numbers: how sure, the biggest hesitation, how full the backpack is.
peekPanels.tiles = (function () {
  let el;
  const vis = t => (t == null ? '—' : '“' + t.trim() + '”');
  return {
    mount(root) {
      el = root;
      el.classList.add('row');
      el.innerHTML = ['sure', 'worst', 'pack'].map(k => `<div class="tile"><div class="cap" id="${k}-cap"></div><div class="big" id="${k}-big">—</div></div>`).join('');
      el.querySelector('#sure-cap').textContent = 'pieces it was sure about';
      el.querySelector('#worst-cap').textContent = 'biggest hesitation';
      el.querySelector('#pack-cap').textContent = 'backpack full';
    },
    onTurn(msg) {
      const t = msg && msg.turn, st = msg && msg.state, s = peekLib.stats(t && t.tokens);
      el.querySelector('#sure-big').textContent = t && t.tokens && t.tokens.length ? s.sure_pct + '%' : '—';
      el.querySelector('#worst-big').textContent = s.worst ? `${vis(s.worst.chosen)} vs ${vis(s.worst.runner)}` : '—';
      el.querySelector('#pack-big').textContent = st && st.window_tokens ? Math.round(100 * st.next_would_send / st.window_tokens) + '%' : '—';
    },
  };
})();
