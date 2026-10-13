/* All messages and forms remain available without JavaScript. */
(() => {
  const filters = document.querySelector('.review-filters');
  if (!filters) return;
  const buttons = [...filters.querySelectorAll('[data-review-filter]')];
  const cards = [...document.querySelectorAll('[data-review-group]')];
  const groups = buttons.map(button => button.dataset.reviewFilter);
  const search = document.getElementById('review-search');
  const count = document.getElementById('review-result-count');
  const empty = document.getElementById('review-no-results');
  let group = 'drafts';
  function filterCards() {
    const query = (search?.value || '').trim().toLocaleLowerCase('de');
    let total = 0;
    let visible = 0;
    cards.forEach(card => {
      const inGroup = card.dataset.reviewGroup === group;
      const isMessage = card.hasAttribute('data-review-search');
      const matches = !query || (card.dataset.reviewSearch || '').toLocaleLowerCase('de').includes(query);
      if (inGroup && isMessage) total++;
      card.hidden = !inGroup || !matches;
      if (!card.hidden && isMessage) visible++;
    });
    if (count) count.textContent = query ? `${visible} von ${total} Nachrichten` : `${total} ${total === 1 ? 'Nachricht' : 'Nachrichten'}`;
    if (empty) empty.hidden = !query || visible > 0;
  }
  function showCurrent() {
    const hash = location.hash.slice(1);
    const target = document.getElementById(hash);
    group = target?.dataset.reviewGroup || (groups.includes(hash) ? hash : 'drafts');
    // A direct draft link must stay visible even after an earlier search.
    if (search) search.value = '';
    filterCards();
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.reviewFilter === group)));
    if (target?.dataset.reviewGroup) target.scrollIntoView({block: 'start'});
  }
  filters.hidden = false;
  const searchControls = document.querySelector('.review-search');
  if (searchControls) searchControls.hidden = false;
  search?.addEventListener('input', filterCards);
  document.getElementById('review-search-reset')?.addEventListener('click', () => {
    search.value = '';
    filterCards();
    search.focus();
  });
  filters.addEventListener('click', event => {
    const button = event.target.closest('[data-review-filter]');
    if (button) {
      if (location.hash === `#${button.dataset.reviewFilter}`) showCurrent();
      else location.hash = button.dataset.reviewFilter;
    }
  });
  window.addEventListener('hashchange', showCurrent);
  showCurrent();
})();
