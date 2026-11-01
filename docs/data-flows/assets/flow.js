document.addEventListener('DOMContentLoaded', () => {
  const cards = document.querySelectorAll('.stage-card');
  cards.forEach((card, i) => {
    const head = card.querySelector('.stage-head');
    if (!head) return;
    head.addEventListener('click', () => card.classList.toggle('open'));
    if (i === 0) card.classList.add('open');
  });

  const expandAllBtn = document.getElementById('expand-all');
  const collapseAllBtn = document.getElementById('collapse-all');
  if (expandAllBtn) expandAllBtn.addEventListener('click', () => cards.forEach((c) => c.classList.add('open')));
  if (collapseAllBtn) collapseAllBtn.addEventListener('click', () => cards.forEach((c) => c.classList.remove('open')));
});
