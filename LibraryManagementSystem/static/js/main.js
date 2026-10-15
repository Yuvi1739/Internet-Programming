document.addEventListener("submit", function (event) {
  const form = event.target;
  if (form.matches("[data-confirm]")) {
    if (!window.confirm(form.dataset.confirm || "Are you sure?")) event.preventDefault();
  }
});
document.querySelectorAll(".flash").forEach((item) => {
  window.setTimeout(() => item.classList.add("flash-fade"), 5000);
});
