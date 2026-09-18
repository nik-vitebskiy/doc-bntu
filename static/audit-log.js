document.addEventListener("click", (event) => {
  const row = event.target.closest("[data-audit-toggle]");
  if (!row || event.target.closest("a")) return;
  toggleAuditRow(row);
});

document.addEventListener("keydown", (event) => {
  const row = event.target.closest("[data-audit-toggle]");
  if (!row || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  toggleAuditRow(row);
});

function toggleAuditRow(row) {
  const details = document.getElementById(row.dataset.auditToggle);
  if (!details) return;
  const expanded = row.getAttribute("aria-expanded") === "true";
  row.setAttribute("aria-expanded", String(!expanded));
  details.hidden = expanded;
}

const highlightedKey = new URLSearchParams(window.location.search).get("audit_highlight");
if (highlightedKey) {
  const statusMark = document.querySelector(`mark[data-status-key="${CSS.escape(highlightedKey)}"]`);
  const target = statusMark?.closest("section, .titlebar") || statusMark;
  if (target) {
    target.classList.add("audit-highlighted-target");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}
