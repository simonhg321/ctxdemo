// "The room": the presenter's live feed of everyone's questions (NFCU). Polls /api/room every 3 s; the server
// answers only on the /presenter/ door when the audience clamp is on. Shows name (if given), question, how sure.
peekPanels.room = (function () {
  let el, timer = null, seen = '';
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const tone = p => (p == null ? '' : p >= 80 ? 'sure' : p >= 50 ? 'unsure' : 'flip');
  function row(t) {
    const who = t.name ? `<b>${esc(t.name)}</b>` : `<span class="dim">#${esc(t.session)}</span>`;
    const sure = t.sure_pct == null ? '' : `<span class="room-sure ${tone(t.sure_pct)}">${t.sure_pct}% sure</span>`;
    const worst = t.worst && t.worst.vs && t.worst.vs.length ? `<span class="dim">· almost “${esc(t.worst.vs[0])}” for “${esc(t.worst.t)}”</span>` : '';
    const persona = t.persona && t.persona !== 'wall' ? `<span class="dim">· as ${esc(t.persona)}</span>` : '';
    return `<div class="room-row"><div class="room-head"><span class="dim">${esc(t.ts)}</span> ${who} ${sure} ${persona} ${worst}</div>` +
      `<div class="room-q">${esc(t.user)}</div><div class="room-a dim">${esc(t.answer)}</div></div>`;
  }
  async function poll() {
    try {
      const r = await fetch('../../api/room');                                  // relative: works under /presenter/ too
      if (r.status === 403) { el.querySelector('#feed').innerHTML = '<span class="dim">presenter only — open this from /presenter/</span>'; return; }
      const turns = (await r.json()).turns || [];
      const key = turns.map(t => t.ts + t.session + t.user).join('|');
      if (key === seen) return; seen = key;
      el.querySelector('#count').textContent = turns.length ? `${turns.length} recent · ${(n => n + (n === 1 ? ' person' : ' people'))(new Set(turns.map(t => t.session)).size)}` : '';
      el.querySelector('#feed').innerHTML = turns.length ? turns.map(row).join('') : '<span class="dim">nobody has asked yet</span>';
    } catch (e) { /* the box is busy or we are offline: keep the last feed */ }
  }
  return {
    mount(root) {
      el = root; el.classList.add('room');
      el.innerHTML = '<div class="wire-head"><div class="cap">the room — what people are asking</div><span id="count" class="dim" style="margin-left:auto;font-size:.8em"></span></div><div id="feed" class="room-feed dim">…</div>';
      poll(); timer = setInterval(poll, 3000);
    },
    onTurn() { poll(); },
  };
})();
