// The driver: the only panel that talks to the server. Everything else listens on the bus.
peekPanels.driver = (function () {
  let el, sid = null, busy = false, lastTurn = null, lastSelect = null, persona = null, web = false, pack = 4096, compact = true;   // web: the web_search tool; window/compact: the backpack size and whether it compacts at 95% (off = overflow on purpose)
  const API = '../../api/';                                  // relative: the app lives under /demo/ behind Caddy
  let audience = false, room = false, toolsOk = true, switching = null;   // Linode: audience = clamped visitor; room = name box on; toolsOk = model has a tool parser; switching = vLLM restarting
  let queueTimer = null;
  const nameOf = () => { const n = el.querySelector('#name'); return n && n.value.trim() ? n.value.trim().slice(0, 24) : undefined; };
  async function watchQueue() {                              // while an answer is in flight: how many others the GPU is serving
    try { const q = (await (await fetch(API + 'queue')).json()).queue; const line = peekLib.queueLine(q); if (busy) status('thinking…' + (line ? '  ·  ' + line : '')); } catch (e) { /* keep the old line */ }
  }
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  async function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; status('thinking…'); el.querySelectorAll('button,input').forEach(b => b.disabled = true);
    watchQueue(); queueTimer = setInterval(watchQueue, 2000);
    try {
      if (!sid) sid = (await post('session', Object.assign({ mode: compact ? 'compact' : 'endless', board: true, peek: true, tools: web, window: pack }, peekLib.personaSessionFields(persona)))).session_id;
      const r = await post('turn', { session_id: sid, text, name: nameOf() });
      sendTurn(r);
      const searched = (r.turn.tool_uses || []).map(u => (u.args || {}).query || u.name).join(' · ');
      status(r.turn.event === 'compacted' ? `the ${peekLib.words().pack} was full — it compacted first` : searched ? 'searched the web: ' + searched : '');
      el.querySelector('#q').value = '';
    } catch (e) { status('error: ' + e.message); if (/no such session/.test(e.message)) sid = null; }   // show the real error; a restart forgets sessions
    clearInterval(queueTimer); queueTimer = null;
    busy = false; el.querySelectorAll('button,input').forEach(b => b.disabled = false); el.querySelector('#q').focus();
  }
  function status(s) { el.querySelector('#st').textContent = s; }
  function sendTurn(msg) {
    const slim = { turn: msg.turn, session_id: sid, state: msg.state ? { window_tokens: msg.state.window_tokens, next_would_send: msg.state.next_would_send } : null };
    lastTurn = slim; lastSelect = null; peekBus.send('turn', slim);
  }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">ask the model</div><form id="f" style="display:flex;gap:.5em"><input type="text" id="q" placeholder="type a question" autocomplete="off"><button>Ask</button></form>' +
        '<div id="asks" style="display:flex;flex-wrap:wrap;gap:.3em;font-size:.8em"></div><div style="display:flex;gap:.5em;align-items:center;flex-wrap:wrap;font-size:.9em"><button id="new" type="button">Start over</button><button id="web" type="button" title="give it web search (a fresh session)">🌐 web: off</button><button id="win" type="button" title="context size (a fresh session)">🎒 4k</button><button id="cmp" type="button" title="when 95% full it writes itself a summary and drops the rest; off = let it overflow (a fresh session)">compact: on</button><input type="text" id="name" placeholder="your first name (optional)" maxlength="24" autocomplete="off" style="width:auto;flex:0 1 14em;display:none" title="shows next to your questions on the presenter\'s screen"><span id="st" class="dim"></span></div>';
      const drawAsks = () => {
        const box = el.querySelector('#asks'); box.innerHTML = '';
        peekLib.asksFor(audience).forEach(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a; b.onclick = () => ask(a); box.appendChild(b); });
        ['#web', '#win', '#cmp'].forEach(id => { el.querySelector(id).style.display = audience ? 'none' : ''; });   // the shared GPU's knobs are the presenter's
        if (!toolsOk) { el.querySelector('#web').style.display = 'none'; if (web) { web = false; el.querySelector('#web').textContent = '🌐 web: off'; } }   // this model cannot call tools
        el.querySelector('#name').style.display = room ? '' : 'none';                                              // the name box feeds the room panel
      };
      drawAsks();
      const applyHealth = h => { audience = !!h.audience; room = !!h.room; toolsOk = h.tools_ok !== false; drawAsks(); };
      fetch(API + 'health').then(r => r.json()).then(applyHealth).catch(() => {});
      peekBus.on('model', d => {                               // the tiles panel polls /api/models and relays: lock the ask box during a switch
        const wasSwitching = !!switching; switching = d.switching || null;
        if (switching) { el.querySelectorAll('button,input').forEach(b => b.disabled = true); status('the model is switching to ' + switching.target.split('/').pop() + ' — about a minute'); }
        else if (wasSwitching) { el.querySelectorAll('button,input').forEach(b => b.disabled = false); sid = null; peekBus.send('clear', {}); status('now answering: ' + (d.current || '').split('/').pop());
          fetch(API + 'health').then(r => r.json()).then(applyHealth).catch(() => {}); }
      });
      el.querySelector('#f').onsubmit = e => { e.preventDefault(); ask(el.querySelector('#q').value); };
      el.querySelector('#new').onclick = () => { sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {}); status(''); };
      const fresh = msg => { sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {}); status(msg); };   // session settings are fixed at session start
      const W = peekLib.words();
      el.querySelector('#win').textContent = W.packIcon + ' ' + pack / 1024 + 'k'; el.querySelector('#win').title = W.pack + ' size (a fresh session)';
      el.querySelector('#win').onclick = () => { pack = { 4096: 8192, 8192: 32768 }[pack] || 4096; el.querySelector("#win").textContent = W.packIcon + " " + pack / 1024 + "k"; fresh(W.pack + ": " + pack + " " + W.pieces); };
      el.querySelector('#cmp').onclick = () => { compact = !compact; el.querySelector('#cmp').textContent = 'compact: ' + (compact ? 'on' : 'off'); fresh(compact ? 'it will compact at 95% full' : 'no compaction — it will overflow'); };
      el.querySelector('#web').onclick = () => {                 // toggling means a fresh session: tools are fixed at session start
        web = !web; sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {});
        el.querySelector('#web').textContent = '🌐 web: ' + (web ? 'on' : 'off'); status(web ? 'it can search the web now' : '');
      };
      peekBus.on('select', d => { if (lastTurn) lastSelect = d; });
      peekBus.on('persona', d => {                              // a persona button was picked: speak as it, starting fresh
        if (persona && persona.id === d.id && persona.title === d.title && persona.prompt === d.prompt) return;   // our own hello re-send: not a real change
        persona = d; sid = null; lastTurn = null; lastSelect = null;
        peekBus.send('clear', {}); status('speaking as: ' + d.title);
      });
      peekBus.on('hello', () => {                              // a panel opened late: repeat the last turn (and persona) for it
        if (persona) peekBus.send('persona', persona);
        if (!lastTurn) return;
        const s = lastSelect;
        peekBus.send('turn', lastTurn); if (s) peekBus.send('select', s);
      });
      if (new URLSearchParams(location.search).get('replay') === '1') {
        fetch('replay.json').then(r => r.json()).then(rp => {
          let i = 0; const play = () => sendTurn(rp.turns[i++ % rp.turns.length]);
          status('replay — no model'); play(); setInterval(play, 16000);
        });
      }
    },
    onTurn() {},
  };
})();
