// Confirmation prompts for destructive/permanent actions (buttons or forms with data-confirm).
document.addEventListener("click", function (e) {
  var btn = e.target.closest("button[data-confirm]");
  if (btn && !window.confirm(btn.getAttribute("data-confirm"))) { e.preventDefault(); }
});
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) { e.preventDefault(); }
});
