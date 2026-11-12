// Shows who is signed in, with a Sign out link that clears the gate cookie (wall, shells and welcome page all end with it).
// Lab users only: the shared key is nobody in particular, so there is no name to show.
(() => {
  const root = new URL('..', document.currentScript.src).href;                   // the site root, wherever the site is mounted (this file lives in static/)
  fetch(root + 'api/me').then(r => r.ok ? r.json() : null).then(d => {
    if (!d || !d.user) return;
    const box = document.createElement('div'); box.id = 'whoami';
    const name = document.createElement('b'); name.textContent = d.user;
    const out = document.createElement('a'); out.href = root + 'gate'; out.textContent = 'Sign out'; out.style.color = 'inherit';
    out.onclick = async e => { e.preventDefault(); await fetch(root + 'api/gate/out', { method: 'POST' }).catch(() => {}); location.replace(root + 'gate'); };
    box.append('Signed in as ', name, ' · ', out);
    const slot = document.querySelector('[data-whoami]');                      // a page with a header gives it a place
    if (slot) { slot.append(box); return; }
    box.style.cssText = 'position:fixed;right:10px;bottom:8px;z-index:25;font:12px system-ui,sans-serif;color:#9aa7b0;background:rgba(16,20,24,.88);padding:4px 10px;border-radius:999px';
    document.body.append(box);                                                   // the big wall has no header: a small pill in the corner
  }).catch(() => {});
})();
