// The driver: the only panel that talks to the server. Everything else listens on the bus.
peekPanels.driver = (function () {
  let el, sid = null, busy = false, lastTurn = null, lastSelect = null, persona = null, web = false, pack = 4096, compact = true;   // web: the web_search tool; window/compact: the backpack size and whether it compacts at 95% (off = overflow on purpose)
  const API = '../../api/';                                  // relative: the app lives under /demo/ behind Caddy
  const ASKS = ['Pick a number between 1 and 10',                                       // short: one real coin-flip
    'Divide by 3 in C using only shifts',                                                 // code: half the pieces uncertain
    'Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?',   // confidently wrong unless it shows its steps
    'List every country in the world with its capital',                                   // long: ~2,700 pieces, stale facts (Astana)
    'Every US president in order, with years and one thing each is remembered for',        // long: dates and hallucination bait
    'Explain how TCP delivers a file, step by step, from SYN to the last ACK'];          // long technical, for an engineer audience
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  async function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; status('thinking…'); el.querySelectorAll('button,input').forEach(b => b.disabled = true);
    try {
      if (!sid) sid = (await post('session', Object.assign({ mode: compact ? 'compact' : 'endless', board: true, peek: true, tools: web, window: pack }, peekLib.personaSessionFields(persona)))).session_id;
      const r = await post('turn', { session_id: sid, text });
      sendTurn(r);
      const searched = (r.turn.tool_uses || []).map(u => (u.args || {}).query || u.name).join(' · ');
      status(r.turn.event === 'compacted' ? 'the backpack was full — it compacted first' : searched ? 'searched the web: ' + searched : '');
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
        '<div id="asks" style="display:flex;flex-wrap:wrap;gap:.3em;font-size:.8em"></div><div style="display:flex;gap:.5em;align-items:center;flex-wrap:wrap;font-size:.9em"><button id="new" type="button">Start over</button><button id="web" type="button" title="give it web search (a fresh session)">🌐 web: off</button><button id="win" type="button" title="backpack size (a fresh session)">🎒 4k</button><button id="cmp" type="button" title="compact at 95% full, or let it overflow (a fresh session)">compact: on</button><span id="st" class="dim"></span></div>';
      ASKS.forEach(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a; b.onclick = () => ask(a); el.querySelector('#asks').appendChild(b); });
      el.querySelector('#f').onsubmit = e => { e.preventDefault(); ask(el.querySelector('#q').value); };
      el.querySelector('#new').onclick = () => { sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {}); status(''); };
      const fresh = msg => { sid = null; lastTurn = null; lastSelect = null; peekBus.send('clear', {}); status(msg); };   // session settings are fixed at session start
      el.querySelector('#win').onclick = () => { pack = { 4096: 8192, 8192: 32768 }[pack] || 4096; el.querySelector("#win").textContent = "🎒 " + pack / 1024 + "k"; fresh("backpack: " + pack + " pieces"); };
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
