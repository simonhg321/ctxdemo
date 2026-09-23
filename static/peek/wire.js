// "How do we know?": the exact bytes of the last model call — the request we posted and the JSON that came back.
// Nothing is instrumented inside vLLM: two flags in a standard OpenAI-style request ask it to keep the numbers it
// already computed. Before the first turn the left side shows the request that WOULD go for the current persona.
peekPanels.wire = (function () {
  let el, model = 'the model', persona = null, wire = null;
  function draft() {
    const p = peekBus.last('persona') || persona;
    return peekLib.wireDraft(model, p ? p.prompt : '(the persona’s instructions go here)', '(your question goes here)');
  }
  function render() {
    const req = el.querySelector('#req'), resp = el.querySelector('#resp'), note = el.querySelector('#note');
    if (wire) {
      req.innerHTML = peekLib.wireHighlight(wire.request);
      resp.innerHTML = peekLib.wireHighlight(wire.response);
      note.textContent = wire.total > wire.shown
        ? `first ${wire.shown} of ${wire.total} ${peekLib.words().pieces} shown — every one carries its probability and its top-5 runners-up`
        : `${wire.total} ${peekLib.words().pieces}, each with its probability and its top-5 runners-up`;
    } else {
      req.innerHTML = peekLib.wireHighlight(draft());
      resp.innerHTML = '<span class="dim">ask something and the reply lands here</span>';
      note.textContent = 'this is what the ask box will send';
    }
  }
  const close = () => peekBus.send('wire', { open: false });
  return {
    mount(root) {
      el = root; el.classList.add('wire');
      el.innerHTML =
        '<div class="wire-head"><div class="cap">how do we know? — the actual request and reply</div>' +
        '<button type="button" id="close" title="Esc">close</button></div>' +
        '<div class="wire-intro">A standard <b>OpenAI-style chat request</b> to vLLM. The two <mark>marked</mark> flags ask the server ' +
        'to keep the probabilities it already computed for every ' + peekLib.words().piece + '. Nothing inside the model is touched or patched.</div>' +
        '<div class="wire-cols"><div><div class="cap">we send</div><pre id="req"></pre></div>' +
        '<div><div class="cap">it answers</div><pre id="resp"></pre><div id="note" class="dim"></div></div></div>';
      el.querySelector('#close').onclick = close;
      document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
      fetch('../../api/health').then(r => r.json()).then(h => { if (h.model) model = h.model; render(); }).catch(render);   // relative: /demo/ prefix
      peekBus.on('persona', d => { persona = d; if (!wire) render(); });
      render();
    },
    onTurn(msg) { wire = (msg && msg.turn && msg.turn.wire) || null; render(); },
  };
})();
