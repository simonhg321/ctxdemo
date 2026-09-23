// The explain bar: a strip of chips fixed across the top of wall.html, each opening a card of teaching copy
// from static/peek/explain/*.md (index in explain.json — add a chip by adding a file + one line there).
// Loaded only by wall.html, and only when ?bar=0 is absent.
(function () {
  const q = new URLSearchParams(location.search), room = q.get('room') || 'wall';
  let cardsData = [], personas = null, openId = null, closeTimer = null;

  const fileId = name => name.replace(/^\d+-/, '').replace(/\.md$/, '');
  const escHtml = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function renderBlocks(blocks) {
    return blocks.map(b => {
      if (b.type === 'p') return `<p>${peekLib.explainInline(peekLib.plainText(b.text))}</p>`;
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

  function open(id) {
    const c = cardsData.find(x => x.id === id); if (!c) return;
    openId = id;
    const card = document.getElementById('explain-card');
    card.innerHTML = `<h2>${escHtml(c.label)}</h2>` + renderBlocks(c.blocks);
    if (c.blocks.some(b => b.type === 'personas')) fillPersonas(card);
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
    try { peekLib.setVocab((await (await fetch('../../api/health')).json()).vocab); } catch (e) { /* default words */ }   // relative: /demo/ prefix
    const files = await (await fetch('explain.json')).json();
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
    peekBus.on('wire', d => { if (d && d.open) pulse('wire'); });
    peekBus.send('hello', {});   // late joiner: ask the driver to repeat the current persona (if any)
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  load();
})();
