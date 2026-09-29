document.querySelectorAll('form[method="post"]').forEach((form) => {
  form.noValidate = true;
  form.addEventListener('submit', (event) => {
    form.querySelectorAll('.client-field-error,.client-error-summary').forEach((node) => node.remove());
    const errors = [];
    const add = (input, message) => {
      if (!input || errors.some((row) => row.input === input)) return;
      errors.push({input, message});
      const note = document.createElement('small');
      note.className = 'field-error client-field-error';
      note.textContent = message;
      input.insertAdjacentElement('afterend', note);
    };
    [...form.elements].forEach((input) => {
      if (!input.name || input.disabled || input.type === 'hidden') return;
      if (input.required && !String(input.value || '').trim()) add(input, 'Обязательное поле.');
      if (input.minLength > 0 && input.value && input.value.length < input.minLength) add(input, `Не менее ${input.minLength} символов.`);
      if (input.pattern && input.value && !(new RegExp(`^(?:${input.pattern})$`)).test(input.value)) add(input, input.title || 'Проверьте формат поля.');
      if (input.name.startsWith('demand_') && input.value !== '') {
        const year = Number(input.name.slice(7));
        if (year < 2026 || year > 2036) add(input, 'Допустимые годы: 2026–2036.');
        else if (!/^\d+$/.test(input.value)) add(input, 'Введите целое неотрицательное число.');
      }
    });
    const start = form.elements.namedItem('start_date') || form.elements.namedItem('signed_date');
    const end = form.elements.namedItem('end_date') || form.elements.namedItem('date_end');
    if (start?.value && end?.value && end.value < start.value) add(end, 'Дата окончания не может быть раньше даты начала.');
    if (!errors.length) return;
    event.preventDefault();
    const summary = document.createElement('div');
    summary.className = 'error-summary client-error-summary';
    summary.setAttribute('role', 'alert');
    summary.innerHTML = `<b>Исправьте ошибки:</b><ul>${errors.map((row) => `<li>${row.message}</li>`).join('')}</ul>`;
    form.prepend(summary);
    errors[0].input.focus();
  });
});
