// The driver: the only panel that talks to the server. Everything else listens on the bus.
peekPanels.driver = (function () {
  let el, sid = null, busy = false;
  const API = '../../api/';                                  // relative: the app lives under /demo/ behind Caddy
  const ASKS = ['Pick a number between 1 and 10', "What's the capital of Australia?", 'Finish this: roses are red, violets are…', 'Write one line about fog'];
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  async function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; status('thinking…'); el.querySelectorAll('button,input').forEach(b => b.disabled = true);
    try {
      if (!sid) sid = (await post('session', { mode: 'compact', board: true, peek: true })).session_id;
      const r = await post('turn', { session_id: sid, text });
      peekBus.send('turn', r);
      status(r.turn.event === 'compacted' ? 'the backpack was full — it compacted first' : '');
    } catch (e) { status('error: ' + e.message); if (/no such session/.test(e.message)) sid = null; }   // show the real error; a restart forgets sessions
    busy = false; el.querySelectorAll('button,input').forEach(b => b.disabled = false); el.querySelector('#q').value = ''; el.querySelector('#q').focus();
  }
  function status(s) { el.querySelector('#st').textContent = s; }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">ask the model</div><form id="f" style="display:flex;gap:.5em"><input type="text" id="q" placeholder="type a question" autocomplete="off"><button>Ask</button></form>' +
        '<div id="asks" style="display:flex;flex-wrap:wrap;gap:.4em"></div><div style="display:flex;gap:.6em;align-items:center"><button id="new" type="button">Start over</button><span id="st" class="dim"></span></div>';
      ASKS.forEach(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a; b.onclick = () => ask(a); el.querySelector('#asks').appendChild(b); });
      el.querySelector('#f').onsubmit = e => { e.preventDefault(); ask(el.querySelector('#q').value); };
      el.querySelector('#new').onclick = () => { sid = null; peekBus.send('clear', {}); status(''); };
      peekBus.on('hello', () => {                              // a panel opened late: repeat the last turn for it
        const t = peekBus.last('turn'), s = peekBus.last('select');
        if (t) peekBus.send('turn', t); if (t && s) peekBus.send('select', s);
      });
      if (new URLSearchParams(location.search).get('replay') === '1') {
        fetch('replay.json').then(r => r.json()).then(rp => {
          let i = 0; const play = () => peekBus.send('turn', rp.turns[i++ % rp.turns.length]);
          status('replay — no model'); play(); setInterval(play, 16000);
        });
      }
    },
    onTurn() {},
  };
})();
