// "Inside the head": how one token of the answer formed, layer by layer, in a 4B sibling of the wall's model.
// Asks /api/layers for the first token after every turn, and for any token tapped in the answer (bus `select`).
peekPanels.layers = (function () {
  let el, sid = null, toks = [], busy = false, which = 'decided', last = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const vis = t => String(t).replace(/^Ġ| /g, '␣').replace(/\n/g, '⏎').replace(/^<\|.*\|>$/, '·');
  function draw(resp, index) {
    const W = peekLib.words();
    const m = peekLib.layersModel(resp, toks[index] ? toks[index].t : null);
    el.querySelector('#how').textContent = index ? `how it chose “${toks[index].t.trim()}”` : 'how it chose the first ' + W.piece;
    const col = el.querySelector('#col');
    col.innerHTML = m.chips.slice().reverse().map(c =>
      `<div class="lchip ${c.tone}${c.decided ? ' decided' : ''}" title="layer ${c.n}: ${esc(c.t)} ${peekLib.pct(c.p)}">` +
      `<span class="ln">${c.n}</span><span class="lt">${esc(vis(c.t))}</span><span class="lp">${peekLib.pct(c.p)}</span>` +
      (c.decided ? '<span class="ldec">decided here</span>' : '') + '</div>').join('');
    const verdict = el.querySelector('#verdict');
    if (m.agree === false) verdict.innerHTML = `the wall said <b>${esc(toks[index].t.trim())}</b> · the sibling would have said <b>${esc(String(m.sibling).trim())}</b>`;
    else if (m.agree === true) verdict.innerHTML = `both say <b>${esc(String(m.sibling).trim())}</b>`;
    else verdict.textContent = '';
    const h = peekLib.attentionHeat(resp, which);
    el.querySelector('#heat').innerHTML = h.cells.map(c => { const w = Number.isFinite(c.w) ? c.w : 0; return `<span class="hcell" style="background:rgba(127,200,232,${(0.08 + 0.72 * w).toFixed(2)})">${esc(vis(c.t))}</span>`; }).join('');
    el.querySelector('#heatcap').textContent = h.layer ? `where it looked · layer ${h.layer}` : '';
    el.querySelector('#meta').textContent = resp ? `${resp.model.split('/').pop()} · ${resp.n_layers} layers · ${resp.seconds}s${resp.cut ? ' · prompt cut to the last ' + resp.tokens.length + ' ' + W.pieces : ''}` : '';
    peekBus.send('layers', { index, decided_at: m.decided_at, agree: m.agree });
  }
  async function ask(index) {
    if (!sid || !toks.length || busy) return;
    busy = true; el.querySelector('#state').textContent = 'reading the layers…';
    try {
      const r = await fetch('../../api/layers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sid, index }) });   // relative: /demo/ prefix
      if (r.status === 503) { el.querySelector('#state').textContent = 'layers are off on this wall'; return; }
      if (!r.ok) { el.querySelector('#state').textContent = 'layers: ' + ((await r.json().catch(() => ({}))).detail || r.statusText); return; }
      last = await r.json(); el.querySelector('#state').textContent = ''; draw(last, index);
    } catch (e) { el.querySelector('#state').textContent = 'layers: ' + e.message; }
    finally { busy = false; }
  }
  return {
    mount(root) {
      el = root; el.classList.add('layers');
      el.innerHTML = '<div class="wire-head"><div class="cap">the model, layer by layer <span class="dim" id="how"></span></div><span id="meta" class="dim" style="margin-left:auto;font-size:.7em"></span></div>' +
        '<div class="dim" style="font-size:.75em">a 4B sibling of the model you are talking to, read layer by layer · <span id="verdict"></span></div>' +
        '<div id="state" class="dim">ask something…</div>' +
        '<div class="lbody"><div id="col" class="lcol"></div><div class="lheat"><div class="cap"><span id="heatcap">where it looked</span> ' +
        '<button type="button" id="hw" class="linkish">early / decided / late</button></div><div id="heat"></div></div></div>';
      el.querySelector('#hw').onclick = () => { which = { decided: 'early', early: 'late', late: 'decided' }[which]; if (last) draw(last, last.index); };
    },
    onTurn(msg) {
      sid = (msg && msg.session_id) || sid; toks = (msg && msg.turn && msg.turn.tokens) || []; last = null;
      el.querySelector('#col').innerHTML = ''; el.querySelector('#heat').innerHTML = ''; el.querySelector('#verdict').textContent = '';
      if (!toks.length) { el.querySelector('#state').textContent = 'ask something…'; return; }
      ask(0);                                                  // the anchor: how the first token of the answer formed
    },
    onSelect(i) { if (toks[i]) ask(i); },
  };
})();
