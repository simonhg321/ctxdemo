// Shows who is signed in, with a Sign out link that clears the gate cookie (wall, shells and welcome page all end with it).
// A shared-key visitor has no name, but gets the link too, so they can come back under a named login.
(() => {
  const root = new URL('..', document.currentScript.src).href;                   // the site root, wherever the site is mounted (this file lives in static/)
  fetch(root + 'api/me').then(r => r.ok ? r.json() : null).then(d => {
    if (!d || !(d.user || d.key)) return;                                       // not signed in, or no gate at all
    const box = document.createElement('div'); box.id = 'whoami';
    const name = document.createElement('b'); name.textContent = d.user;
    const out = document.createElement('a'); out.href = root + 'gate'; out.textContent = 'Sign out'; out.style.color = 'inherit';
    out.onclick = async e => { e.preventDefault(); await fetch(root + 'api/gate/out', { method: 'POST' }).catch(() => {}); location.replace(root + 'gate'); };
    const shell = document.createElement('a'); shell.href = root + 'shell/'; shell.textContent = 'My shell'; shell.target = '_blank'; shell.rel = 'noopener'; shell.style.color = 'inherit';
    if (d.user) box.append('Signed in as ', name, ' · ', shell, ' · ', out);     // shells belong to named logins; the shared key has none
    else box.append('In on the shared key · ', out);
    const slot = document.querySelector('[data-whoami]');                      // a page with a header gives it a place
    if (slot) { slot.append(box); return; }
    box.style.cssText = 'position:fixed;right:10px;bottom:8px;z-index:25;font:12px system-ui,sans-serif;color:#9aa7b0;background:rgba(16,20,24,.88);padding:4px 10px;border-radius:999px';
    document.body.append(box);                                                   // the big wall has no header: a small pill in the corner
  }).catch(() => {});
})();
