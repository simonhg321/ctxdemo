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
  function gpuTile(busy) {                         // "GPU busy" — the whole room's load on the one card (Netdata via /api/gpu); absent when unconfigured
    let t = el.querySelector('#gpu-tile');
    if (busy == null) { if (t) t.remove(); return; }
    if (!t) {
      t = document.createElement('div'); t.className = 'tile'; t.id = 'gpu-tile';
      t.innerHTML = '<div class="cap">GPU busy right now</div><div class="big" id="gpu-big"></div>';
      el.appendChild(t);
    }
    t.querySelector('#gpu-big').textContent = busy + '%';
    t.classList.toggle('hot', busy >= 90);
  }
  // the people-here tile: this browser says "still here" every 5 s under an id it made up; the answer is the head count + the GPU's line.
  let hereId = null;
  function myId() {
    if (hereId) return hereId;
    const make = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
    try { hereId = localStorage.getItem('ctxdemo_here'); if (!hereId) { hereId = make(); localStorage.setItem('ctxdemo_here', hereId); } } catch (e) { hereId = make(); }   // private window: an id for this page only
    return hereId;
  }
  function hereTile(n, q) {
    const m = peekLib.hereTile(n, q); let t = el.querySelector('#here-tile');
    if (!m) { if (t) t.remove(); return; }
    if (!t) {
      t = document.createElement('div'); t.className = 'tile'; t.id = 'here-tile';
      t.innerHTML = '<div class="cap" id="here-cap"></div><div class="big" id="here-big"></div><div class="dim" id="here-sub" style="font-size:.7em"></div>';
      el.appendChild(t);
    }
    t.querySelector('#here-cap').textContent = m.cap; t.querySelector('#here-big').textContent = m.big; t.querySelector('#here-sub').textContent = m.sub;
    t.classList.toggle('hot', !!(q && q.waiting));                 // red when someone is waiting in line
  }
  async function pollHere() {
    try {
      const r = await fetch('../../api/here', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: myId() }) });
      const j = await r.json(); hereTile(j.here, j.queue);
    } catch (e) { /* keep the last number */ }
  }
  async function pollGpu() {
    try { const g = (await (await fetch('../../api/gpu')).json()).gpu; gpuTile(g ? g.busy : null); } catch (e) { /* keep the last number */ }
  }
  // the model tile: which model is answering, and (with the admin password) a switch to another from config/models.json.
  // A switch restarts vLLM (~1 min when the weights are cached); the tile counts, and the driver disables Ask meanwhile.
  let models = null, pickOpen = false;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function modelTile() {
    if (!models) return;
    let t = el.querySelector('#model-tile');
    if (!t) {
      t = document.createElement('div'); t.className = 'tile model'; t.id = 'model-tile';
      t.innerHTML = '<div class="cap">the model <span class="dim" id="model-hint"></span></div><div id="model-pick" style="display:none"></div><div class="big" id="model-big"></div><div id="model-sub" class="dim"></div>';
      el.appendChild(t);
      t.querySelector('#model-big').onclick = () => { if (models.enabled && !models.switching) { pickOpen = !pickOpen; modelTile(); } };
    }
    const cur = (models.models || []).find(m => m.current) || { label: models.current || '—', note: '' };
    const sw = models.switching;
    if (sw) {
      const target = (models.models || []).find(m => m.id === sw.target) || { label: sw.target };
      const secs = Math.max(0, Math.round(Date.now() / 1000 - sw.since));
      t.querySelector('#model-big').textContent = 'switching → ' + target.label;
      t.querySelector('#model-sub').textContent = `restarting the model server · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')} · usually about a minute`;
      pickOpen = false;
    } else {
      t.querySelector('#model-big').textContent = cur.label;
      t.querySelector('#model-sub').textContent = models.error ? 'last switch failed: ' + models.error : (cur.note || '');
      t.querySelector('#model-hint').textContent = models.enabled ? (pickOpen ? '· pick one above' : '· tap the name to switch (needs the password)') : '';
    }
    t.classList.toggle('switching', !!sw);
    const pick = t.querySelector('#model-pick');
    pick.style.display = pickOpen ? '' : 'none';
    if (pickOpen && !pick.innerHTML) {
      pick.innerHTML = '<select id="model-sel">' + models.models.map(m =>
        `<option value="${esc(m.id)}"${m.current ? ' selected' : ''}>${esc(m.label)} — ${esc(m.note)}${m.cached ? '' : ' (not downloaded: slow)'}</option>`).join('') +
        '</select><input type="password" id="model-pw" placeholder="password" autocomplete="off"><button type="button" id="model-go">Switch</button><span id="model-msg" class="dim"></span>' +
        '<div class="dim"><a href="#" id="model-about">what are these models? →</a></div>';
      pick.querySelector('#model-about').onclick = e => { e.preventDefault(); peekBus.send('explain', { id: 'models' }); };   // opens the "the models" card on the wall
      let sure = false;                                             // others are here and the presenter said "switch anyway"
      const go = pick.querySelector('#model-go'), msg = pick.querySelector('#model-msg');
      const calm = text => { sure = false; go.textContent = 'Switch'; msg.textContent = text || ''; };
      pick.querySelector('#model-sel').onchange = () => calm('');
      go.onclick = async () => {
        const id = pick.querySelector('#model-sel').value, pw = pick.querySelector('#model-pw').value;
        const r = await fetch('../../api/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ id, password: pw, here: myId() }, sure ? { confirm: true } : {})) });
        if (!r.ok) {
          const d = (await r.json().catch(() => ({}))).detail;
          if (d && d.busy) { sure = true; go.textContent = 'Switch anyway'; msg.textContent = d.message + '. A switch takes the wall away from everyone for a minute or more.'; return; }
          calm(typeof d === 'string' ? d : r.statusText); return;
        }
        calm(''); pick.querySelector('#model-pw').value = ''; pickOpen = false; pollModels();
      };
    }
  }
  async function pollModels() {
    try {
      const j = await (await fetch('../../api/models')).json();
      const was = models && models.switching, now = j.switching;
      models = j; modelTile();
      if (now || was) peekBus.send('model', { switching: now, current: j.current });      // ticking while switching, and one final "done"
    } catch (e) { /* keep the last state */ }
  }
  return {
    mount(root) {
      el = root;
      el.classList.add('row');
      pollGpu(); setInterval(pollGpu, 2000);
      pollModels(); setInterval(pollModels, 3000);
      setTimeout(pollHere, 0); setInterval(pollHere, 5000);          // after the three number tiles are drawn (innerHTML below would wipe an earlier tile)
      el.innerHTML = ['sure', 'worst', 'pack'].map(k => `<div class="tile"><div class="cap" id="${k}-cap"></div><div class="big" id="${k}-big">—</div>${k === 'worst' ? '<div class="dim" id="worst-sub"></div>' : ''}</div>`).join('');
      const W = peekLib.words();
      el.querySelector('#sure-cap').textContent = W.pieces + ' it was sure about';
      el.querySelector('#worst-cap').textContent = 'biggest hesitation';
      el.querySelector('#pack-cap').textContent = W.pack + ' used';
      peekBus.on('persona', d => personaTile(d.title));   // driver re-sends this on hello, so a late-joining tiles panel lights up too
    },
    onTurn(msg) {
      const t = msg && msg.turn, st = msg && msg.state, s = peekLib.stats(t && t.tokens);
      el.querySelector('#sure-big').innerHTML = t && t.tokens && t.tokens.length ? `${s.sure_pct}% <span class="dim" style="font-size:.55em">${s.sure_n} of ${s.n}</span>` : '—';
      el.querySelector('#worst-big').textContent = s.worst ? `${vis(s.worst.chosen)} vs ${vis(s.worst.runner)}` : '—';
      el.querySelector('#worst-sub').textContent = s.worst && s.worst.runner_p != null ? `${peekLib.pct(s.worst.p)} vs ${peekLib.pct(s.worst.runner_p)}` : '';   // the odds: the whole lesson in one line
      el.querySelector('#pack-big').textContent = st && st.window_tokens ? Math.round(100 * st.next_would_send / st.window_tokens) + '%' : '—';
    },
  };
})();
