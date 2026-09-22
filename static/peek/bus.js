// The bus: panels in separate windows/iframes of ONE Chrome talk over BroadcastChannel. No server involved.
(function () {
  const handlers = {}, cache = {};
  let ch = null;
  function deliver(msg) {
    if (!msg || msg.v !== 1) return;
    cache[msg.type] = msg.data;
    (handlers[msg.type] || []).forEach(fn => { try { fn(msg.data); } catch (e) { console.error('peek panel', e); } });
  }
  window.peekBus = {
    join(room) { ch = new BroadcastChannel('ctxdemo-peek-' + (room || 'wall')); ch.onmessage = e => deliver(e.data); },
    send(type, data) { const msg = { v: 1, type, data }; deliver(msg); if (ch) ch.postMessage(msg); },   // BroadcastChannel never echoes to the sender
    on(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    last(type) { return cache[type]; },
  };
})();
