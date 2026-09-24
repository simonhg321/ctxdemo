// The explain bar: a strip of chips fixed across the top of wall.html, each opening a card of teaching copy
// from static/peek/explain/*.md (index in explain.json — add a chip by adding a file + one line there).
// Loaded only by wall.html, and only when ?bar=0 is absent.
(function () {
  const q = new URLSearchParams(location.search), room = q.get('room') || 'wall';
  let cardsData = [], personas = null, openId = null, closeTimer = null, health = null;
  let sampling = { temperature: 0, top_p: 1, top_k: -1, repetition_penalty: 1 };   // the dials, live on the wall (greedy until touched)

  const fileId = name => name.replace(/^\d+-/, '').replace(/\.md$/, '');
  const escHtml = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function renderBlocks(blocks) {
    return blocks.map(b => {
      if (b.type === 'p') return `<p>${peekLib.explainInline(peekLib.fillVars(peekLib.plainText(b.text), health))}</p>`;
      if (b.type === 'ul') return `<ul>${b.items.map(i => `<li>${peekLib.explainInline(peekLib.plainText(i))}</li>`).join('')}</ul>`;
      if (b.type === 'personas') return '<div id="explain-personas" class="dim">loading…</div>';
      return '';
    }).join('');
  }

  async function fillPersonas(card) {
    const slot = card.querySelector('#explain-personas'); if (!slot) return;
    if (!personas) personas = (await (await fetch('../../api/personas')).json()).personas || [];   // relative: /demo/ prefix
    const active = peekBus.last('persona');
    slot.classList.remove('dim');
    slot.innerHTML = personas.map(p => {
      const body = p.prompt ? peekLib.explainInline(p.prompt) : '<span class="dim"><i>— no instructions —</i></span>';
      return `<div class="explain-persona${active && active.id === p.id ? ' active' : ''}">` +
        `<div><b>${peekLib.explainInline(p.title)}</b></div><div class="explain-persona-body">${body}</div></div>`;
    }).join('');
  }

  function pulse(id) {
    const chip = document.querySelector(`.explain-chip[data-id="${id}"]`); if (!chip) return;
    chip.classList.remove('pulse'); void chip.offsetWidth;   // restart the animation if it's already mid-pulse
    chip.classList.add('pulse');
    chip.addEventListener('animationend', () => chip.classList.remove('pulse'), { once: true });   // no timer left running
  }
  function personaSuffix(title) {
    const chip = document.querySelector('.explain-chip[data-id="persona"]'); if (!chip) return;
    let s = chip.querySelector('.explain-chip-sub');
    if (!title) { if (s) s.remove(); return; }
    if (!s) { s = document.createElement('span'); s.className = 'explain-chip-sub'; chip.appendChild(s); }
    s.textContent = ' · ' + title;
  }

  const DIALS = [
    { k: 'temperature', label: 'temperature', min: 0, max: 1.5, step: 0.05, hint: '0 = greedy. 0.6 is what most chat apps use.' },
    { k: 'top_p', label: 'top-p', min: 0.05, max: 1, step: 0.05, hint: 'only roll among the tokens that together cover this much of the odds' },
    { k: 'top_k', label: 'top-k', min: 0, max: 100, step: 1, hint: 'only the best k tokens are in the hat (0 = off)' },
    { k: 'repetition_penalty', label: 'repeat penalty', min: 1, max: 1.5, step: 0.05, hint: 'a tax on any token that already appeared (1 = none)' },
  ];
  function samplingSuffix() {
    const chip = document.querySelector('.explain-chip[data-id="temperature"]'); if (!chip) return;
    let s = chip.querySelector('.explain-chip-sub');
    const line = peekLib.samplingLine(sampling);
    if (line === 'greedy') { if (s) s.remove(); return; }
    if (!s) { s = document.createElement('span'); s.className = 'explain-chip-sub'; chip.appendChild(s); }
    s.textContent = ' · ' + line.replace('temperature ', '');
  }
  function renderDials(card) {                              // the temperature card is live: the dials apply to the next question asked on this wall
    const box = document.createElement('div'); box.id = 'sampling-controls';
    box.innerHTML = '<div class="cap">the dials — live, they apply to your next question</div>' +
      DIALS.map(d => `<label class="dial"><span class="dial-name">${d.label}</span><input type="range" data-k="${d.k}" min="${d.min}" max="${d.max}" step="${d.step}" value="${sampling[d.k] === -1 ? 0 : sampling[d.k]}"><span class="dial-val" id="dial-${d.k}"></span><span class="dim dial-hint">${d.hint}</span></label>`).join('') +
      `<div class="dial-foot"><span id="dial-line" class="dim"></span><button type="button" id="dial-greedy">back to greedy</button></div>`;
    box.addEventListener('click', e => e.stopPropagation());   // the overlay closes on any click; not while someone is turning a dial
    const readout = () => {
      DIALS.forEach(d => { const v = sampling[d.k]; document.getElementById('dial-' + d.k).textContent = d.k === 'top_k' && v === -1 ? 'off' : String(v); });
      const line = peekLib.samplingLine(sampling);
      document.getElementById('dial-line').textContent = line === 'greedy' ? 'greedy: the most likely token, every time (temperature 0)' : line;
      samplingSuffix();
    };
    box.querySelectorAll('input[type=range]').forEach(inp => {
      inp.addEventListener('input', () => {
        const k = inp.dataset.k, v = Number(inp.value);
        sampling[k] = k === 'top_k' ? (v < 1 ? -1 : Math.round(v)) : Math.round(v * 100) / 100;
        readout(); clearTimeout(closeTimer); closeTimer = setTimeout(close, 45000);
        peekBus.send('sampling', peekLib.cleanSampling(sampling) || { temperature: 0 });
      });
    });
    box.querySelector('#dial-greedy').addEventListener('click', () => {
      sampling = { temperature: 0, top_p: 1, top_k: -1, repetition_penalty: 1 };
      box.querySelectorAll('input[type=range]').forEach(inp => { inp.value = sampling[inp.dataset.k] === -1 ? 0 : sampling[inp.dataset.k]; });
      readout(); peekBus.send('sampling', { temperature: 0 });
    });
    card.insertBefore(box, card.children[1] || null); readout();   // right under the title: the dials are the point of this card, the prose is the footnote
  }

  function open(id) {
    const c = cardsData.find(x => x.id === id); if (!c) return;
    openId = id;
    const card = document.getElementById('explain-card');
    card.innerHTML = `<h2>${escHtml(c.label)}</h2>` + renderBlocks(c.blocks);
    if (c.blocks.some(b => b.type === 'personas')) fillPersonas(card);
    if (id === 'temperature') renderDials(card);
    document.getElementById('explain-overlay').classList.add('open');
    clearTimeout(closeTimer); closeTimer = setTimeout(close, 45000);   // unattended wall: never stays covered
  }
  function close() {
    openId = null; clearTimeout(closeTimer); closeTimer = null;
    document.getElementById('explain-overlay').classList.remove('open');
  }
  function toggle(id) { openId === id ? close() : open(id); }

  function buildBar() {
    const bar = document.createElement('div'); bar.id = 'explain-bar';
    cardsData.forEach(c => {
      const chip = document.createElement('button');
      chip.type = 'button'; chip.className = 'explain-chip'; chip.dataset.id = c.id;
      chip.innerHTML = `<span class="explain-chip-label">${escHtml(c.label)}</span>`;
      chip.addEventListener('click', () => toggle(c.id));
      bar.appendChild(chip);
    });
    const help = document.createElement('button');
    help.type = 'button'; help.className = 'explain-chip explain-chip-help'; help.textContent = '?';
    help.title = cardsData[cardsData.length - 1].label;
    help.addEventListener('click', () => toggle(cardsData[cardsData.length - 1].id));
    bar.appendChild(help);
    document.body.appendChild(bar);
    document.body.classList.add('explain-bar-active');   // hook for wall.html to shift the iframe container down

    const overlay = document.createElement('div'); overlay.id = 'explain-overlay';
    overlay.innerHTML = '<div id="explain-card"></div>';
    overlay.addEventListener('click', close);   // tap anywhere — backdrop or card — closes (click event bubbles from the card)
    document.body.appendChild(overlay);
  }

  async function load() {
    try { health = await (await fetch('../../api/health')).json(); peekLib.setVocab(health.vocab); } catch (e) { /* default words */ }   // relative: /demo/ prefix
    const files = peekLib.chipsFor(await (await fetch('explain.json')).json(), health);
    cardsData = await Promise.all(files.map(async name => {
      const text = await (await fetch('explain/' + name)).text();
      const parsed = peekLib.explainParse(text);
      return Object.assign({ id: fileId(name) }, parsed, { label: peekLib.plainText(parsed.label) });
    }));
    buildBar();
    peekBus.join(room);
    peekBus.on('turn', () => pulse('guesses'));
    peekBus.on('persona', d => { personaSuffix(d.title); pulse('persona'); });
    peekBus.on('clear', () => personaSuffix(null));
    peekBus.on('hello', () => { const c = peekLib.cleanSampling(sampling); if (c) peekBus.send('sampling', c); });   // a late driver learns the dials
    peekBus.on('wire', d => { if (d && d.open) pulse('wire'); });
    peekBus.on('layers', () => pulse('layers'));
    peekBus.on('model', d => { if (d && !d.switching) fetch('../../api/health').then(r => r.json()).then(h => { health = h; }).catch(() => {}); });   // the card names the running model
    peekBus.send('hello', {});   // late joiner: ask the driver to repeat the current persona (if any)
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  load();
})();
