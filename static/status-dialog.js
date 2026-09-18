document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-open-status-dialog]').forEach((button) => {
    button.addEventListener('click', () => document.getElementById(button.dataset.openStatusDialog).showModal());
  });

  document.querySelectorAll('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog').close());
  });

  document.querySelectorAll('.status-form').forEach((form) => {
    const select = form.querySelector('[name="status"]');
    const comment = form.querySelector('[name="comment"]');
    const error = form.querySelector('.status-error');
    const refreshRequired = () => {
      const reverseApplication = form.dataset.documentType === 'application'
        && form.dataset.currentStatus !== 'Заявка'
        && select.value === 'Заявка';
      const closingRequiresComment = form.dataset.documentType !== 'contract'
        && select.value === 'Закрыт';
      comment.required = closingRequiresComment || reverseApplication;
    };
    select.addEventListener('change', refreshRequired);
    refreshRequired();

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.textContent = '';
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form) });
      const data = await response.json();
      if (!response.ok) {
        error.textContent = data.error || 'Не удалось изменить статус.';
        return;
      }
      document.querySelectorAll(`mark[data-status-key="${form.dataset.statusKey}"]`).forEach((badge) => {
        badge.textContent = data.status;
        badge.className = data.status_class;
        badge.dataset.statusKey = form.dataset.statusKey;
      });
      form.dataset.currentStatus = data.status;
      select.replaceChildren(...data.transitions.map((status) => {
        const option = document.createElement('option');
        option.value = status;
        option.textContent = status;
        return option;
      }));
      comment.value = '';
      refreshRequired();
      form.closest('dialog').close();
      if (!data.transitions.length) {
        document.querySelector(`[data-open-status-dialog="${form.closest('dialog').id}"]`)?.setAttribute('hidden', '');
      }
    });
  });
});
