// Bridge to whatever hosts the page: the native app (WKWebView message handler `pet`) or a plain browser
// (development harness). The page never talks to the network; everything it knows arrives here.

export function createHost() {
  const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pet;
  const listeners = [];
  const host = {
    native: Boolean(handler),
    log: [],
    post(message) {
      if (handler) handler.postMessage(message);
      else if (window.parent !== window) window.parent.postMessage({ fromPet: message }, '*');
      else {
        host.log.push(message);
        if (host.log.length > 200) host.log.shift();
        if (window.__PET_DEBUG__) console.debug('[pet→host]', message);
      }
    },
    subscribe(callback) {
      listeners.push(callback);
    },
  };
  const deliver = (message) => { for (const l of listeners) l(message); };
  // The native host calls AgentPet.receive(...) through evaluateJavaScript.
  window.AgentPet = Object.assign(window.AgentPet || {}, { receive: deliver });
  window.addEventListener('message', (e) => { if (e.data && e.data.toPet) deliver(e.data.toPet); });
  return host;
}

/** In a browser there is no native overlay, so translate DOM pointer events into the host's vocabulary. */
export function installDomPointer(root, deliver) {
  const at = (e) => { const r = root.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  let down = null;
  root.addEventListener('pointermove', (e) => deliver({ type: 'pointer', ev: 'move', ...at(e) }));
  root.addEventListener('pointerleave', () => deliver({ type: 'pointer', ev: 'leave' }));
  root.addEventListener('pointerdown', (e) => { if (e.button === 0) down = { ...at(e), t: performance.now() }; });
  root.addEventListener('pointerup', (e) => {
    const p = at(e);
    if (e.button === 0 && down && Math.hypot(p.x - down.x, p.y - down.y) < 5) deliver({ type: 'pointer', ev: 'click', ...p });
    down = null;
  });
  root.addEventListener('dblclick', (e) => deliver({ type: 'pointer', ev: 'dblclick', ...at(e) }));
  root.addEventListener('contextmenu', (e) => { e.preventDefault(); deliver({ type: 'pointer', ev: 'right', ...at(e) }); });
  window.addEventListener('pointermove', (e) => { const r = root.getBoundingClientRect(); deliver({ type: 'cursor', x: e.clientX - r.left, y: e.clientY - r.top }); });
}
