document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-persist-checkbox]").forEach((checkbox) => {
    const key = checkbox.dataset.persistCheckbox;
    if (!key) return;

    checkbox.checked = localStorage.getItem(key) === "true";
    checkbox.addEventListener("change", () => {
      localStorage.setItem(key, String(checkbox.checked));
    });
  });
});
