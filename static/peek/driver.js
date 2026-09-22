// The driver: the only panel that talks to the server. Everything else listens on the bus.
peekPanels.driver = (function () {
  let el, sid = null, busy = false, lastTurn = null, lastSelect = null, persona = null;
  const API = '../../api/';                                  // relative: the app lives under /demo/ behind Caddy
  const ASKS = ['Pick a number between 1 and 10', 'Write one line about fog', 'Name a colour, then a fruit, then a city', 'Finish this: roses are red, violets are…'];
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  async function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; status('thinking…'); el.querySelectorAll('button,input').forEach(b => b.disabled = true);
    try {
      if (!sid) sid = (await post('session', Object.assign({ mode: 'compact', board: true, peek: true }, peekLib.personaSessionFields(persona)))).session_id;
      const r = await post('turn', { session_id: sid, text });
      sendTurn(r);
      status(r.turn.event === 'compacted' ? 'the backpack was full — it compacted first' : '');
      el.querySelector('#q').value = '';
    } catch (e) { status('error: ' + e.message); if (/no such session/.test(e.message)) sid = null; }   // show the real error; a restart forgets sessions
    busy = false; el.querySelectorAll('button,input').forEach(b => b.disabled = false); el.querySelector('#q').focus();
  }
  function status(s) { el.querySelector('#st').textContent = s; }
  function sendTurn(msg) {
    const slim = { turn: msg.turn, state: msg.state ? { window_tokens: msg.state.window_tokens, next_would_send: msg.state.next_would_send } : null };
    lastTurn = slim; lastSelect = null; peekBus.send('turn', slim);
  }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">ask the model</div><form id="f" style="display:flex;gap:.5em"><input type="text" id="q" placeholder="type a question" autocomplete="off"><button>Ask</button></form>' +
        '<div id="asks" style="display:flex;flex-wrap:wrap;gap:.4em"></div><div style="display:flex;gap:.6em;align-items:center"><button id="new" type="button">Start over</button><span id="st" class="dim"></span></div>';
      ASKS.forEach(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a; b.onclick = () => ask(a); el.querySelector('#asks').appendChild(b); });
      el.querySelector('#f').onsubmit = e => { e.preventDefault(); ask(el.querySelector('#q').value); };
      el.querySelector('#new').onclick = () => { sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {}); status(''); };
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
