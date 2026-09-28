const normalizeSpecialtyText = (value) => value.trim().toLocaleLowerCase('ru-RU');

document.querySelectorAll('[data-specialty-picker]').forEach((picker) => {
  const search = picker.querySelector('.specialty-search');
  const value = picker.querySelector('input[name="specialty"]');
  const optionsPanel = picker.querySelector('.specialty-options');
  const options = [...picker.querySelectorAll('[data-specialty-option]')];
  const empty = picker.querySelector('.specialty-empty');
  const error = picker.querySelector('.specialty-error');

  const setOpen = (open) => {
    picker.classList.toggle('is-open', open);
    optionsPanel.hidden = !open;
    search.setAttribute('aria-expanded', String(open));
  };

  const filter = () => {
    const selectedOption = options.find((option) => option.dataset.value === value.value);
    const query = selectedOption && search.value === selectedOption.dataset.label
      ? ''
      : normalizeSpecialtyText(search.value);
    let visible = 0;
    options.forEach((option) => {
      const matches = !query || option.dataset.searchText.includes(query);
      option.hidden = !matches;
      if (matches) visible += 1;
    });
    empty.hidden = visible !== 0;
  };

  const open = () => {
    filter();
    setOpen(true);
  };

  search.addEventListener('focus', open);
  search.addEventListener('click', open);
  search.addEventListener('input', () => {
    value.value = '';
    error.textContent = '';
    open();
  });

  options.forEach((option) => option.addEventListener('click', () => {
    value.value = option.dataset.value;
    search.value = option.dataset.label;
    error.textContent = '';
    setOpen(false);
  }));

  picker.closest('form')?.addEventListener('submit', (event) => {
    if (!value.value) {
      event.preventDefault();
      error.textContent = 'Выберите специальность из справочника.';
      search.focus();
      open();
    }
  });

  picker.closest('[data-order-item-row]')?.addEventListener('click', (event) => {
    if (event.target.closest('button, a, select, input:not(.specialty-search)')) return;
    open();
  });

  document.addEventListener('click', (event) => {
    if (!picker.contains(event.target)) setOpen(false);
  });

  picker.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
  });
});
