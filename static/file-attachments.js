document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-file-block]").forEach((block) => {
    const zone = block.querySelector("[data-file-dropzone]");
    const input = zone?.querySelector("input[type=file]");
    const name = zone?.querySelector("[data-file-name]");
    if (!zone || !input || !name) return;
    const showName = () => { name.textContent = input.files?.[0]?.name || "Файл не выбран"; };
    input.addEventListener("change", showName);
    ["dragenter", "dragover"].forEach((eventName) => zone.addEventListener(eventName, (event) => { event.preventDefault(); zone.classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach((eventName) => zone.addEventListener(eventName, (event) => { event.preventDefault(); zone.classList.remove("is-dragging"); }));
    zone.addEventListener("drop", (event) => {
      if (!event.dataTransfer?.files?.length) return;
      const transfer = new DataTransfer();
      transfer.items.add(event.dataTransfer.files[0]);
      input.files = transfer.files;
      showName();
    });
  });
});
