// "The chunks": the student's sentence cut into the pieces the model actually reads.
peekPanels.chunks = (function () {
  let el;
  const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  return {
    mount(root) { el = root; el.innerHTML = '<div class="cap">what the model reads</div><div id="strip" class="dim">ask something…</div><div id="count" class="dim"></div>'; },
    onTurn(msg) {
      const t = msg && msg.turn, strip = el.querySelector('#strip'), count = el.querySelector('#count');
      if (!t) { strip.textContent = 'ask something…'; strip.className = 'dim'; count.textContent = ''; return; }
      const ch = t.user_chunks || [];
      strip.className = '';
      if (!ch.length) { strip.textContent = t.user; count.textContent = ''; return; }     // no tokenizer on this server: show the sentence plain
      strip.innerHTML = ch.map(c => `<span class="chunk">${esc(c)}</span>`).join('');
      const words = t.user.trim().split(/\s+/).length;
      count.textContent = `${words} word${words === 1 ? '' : 's'} → ${ch.length} ${peekLib.words().pieces}`;
    },
  };
})();
