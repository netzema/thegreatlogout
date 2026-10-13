/* Progressive filtering: all messages remain available without JavaScript. */
(() => {
  const filters = document.querySelector('.review-filters');
  if (!filters) return;
  const buttons = [...filters.querySelectorAll('[data-review-filter]')];
  const cards = [...document.querySelectorAll('[data-review-group]')];
  const groups = buttons.map(button => button.dataset.reviewFilter);
  function showCurrent() {
    const hash = location.hash.slice(1);
    const target = document.getElementById(hash);
    const group = target?.dataset.reviewGroup || (groups.includes(hash) ? hash : 'drafts');
    cards.forEach(card => { card.hidden = card.dataset.reviewGroup !== group; });
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.reviewFilter === group)));
    if (target?.dataset.reviewGroup) target.scrollIntoView({block: 'start'});
  }
  filters.hidden = false;
  filters.addEventListener('click', event => {
    const button = event.target.closest('[data-review-filter]');
    if (button) location.hash = button.dataset.reviewFilter;
  });
  window.addEventListener('hashchange', showCurrent);
  showCurrent();
})();
