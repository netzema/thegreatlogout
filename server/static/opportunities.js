/* Refresh only preparation cards; never disturb the manual occasion form. */
(() => {
  let timer;
  async function refresh() {
    const list = document.getElementById('opportunity-list');
    if (!list || document.hidden) { timer = setTimeout(refresh, 10000); return; }
    if (!list.querySelector('[data-preparation="queued"], [data-preparation="running"], [data-preparation=""]')) return;
    try {
      const response = await fetch('/opportunities', {credentials: 'same-origin'});
      if (!response.ok || response.redirected) return;
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = doc.getElementById('opportunity-list');
      if (next && !list.contains(document.activeElement)) list.replaceChildren(...next.childNodes);
    } catch (_) { /* A transient outage must not remove the last visible result. */ }
    timer = setTimeout(refresh, 10000);
  }
  timer = setTimeout(refresh, 10000);
  window.addEventListener('pagehide', () => clearTimeout(timer));
})();
