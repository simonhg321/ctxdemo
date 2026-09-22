// The persona panel: pick who the model answers as. Fetches the list once; the driver owns sessions and resets them.
peekPanels.persona = (function () {
  let el, personas = [], active = null;
  function render() {
    const btns = el.querySelector('#btns');
    btns.innerHTML = peekLib.personaModel(personas, active).map(p =>
      `<button type="button" class="persona-btn${p.active ? ' active' : ''}" data-id="${p.id}">` +
      `<div class="t">${p.title}</div><div class="b dim">${p.blurb}</div></button>`).join('');
    btns.querySelectorAll('button').forEach(b => b.onclick = () => pick(b.dataset.id));
    el.querySelector('#custom').classList.toggle('active', active === 'custom');
  }
  function pick(id) {
    const p = personas.find(p => p.id === id); if (!p) return;
    active = id;
    peekBus.send('persona', { id: p.id, title: p.title, prompt: p.prompt });
    render();
  }
  return {
    mount(root) {
      el = root;
      el.classList.add('persona');
      el.innerHTML = '<div class="cap">speak as</div><div id="btns" class="persona-list"></div>' +
        '<button type="button" id="custom">Custom…</button>' +
        '<div id="custom-form" class="dim" style="display:none">' +
        '<textarea id="custom-text" rows="3" placeholder="system prompt"></textarea>' +
        '<button type="button" id="use">Use it</button></div>';
      fetch('../../api/personas').then(r => r.json()).then(d => { personas = d.personas || []; render(); });   // relative: /demo/ prefix
      el.querySelector('#custom').onclick = () => {
        const f = el.querySelector('#custom-form'); f.style.display = f.style.display === 'none' ? 'block' : 'none';
      };
      el.querySelector('#use').onclick = () => {
        const text = el.querySelector('#custom-text').value.trim(); if (!text) return;
        active = 'custom';
        peekBus.send('persona', { id: 'custom', title: 'Custom', prompt: text });
        render();
      };
      peekBus.on('persona', d => { active = d.id; render(); });   // driver re-sends this on hello: lights a late-joining panel
    },
    onTurn() {},
  };
})();
