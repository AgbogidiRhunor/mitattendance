// Shared behaviour: confirmations, mobile menu sheet, dismissible messages.
document.addEventListener("click", function (e) {
  var btn = e.target.closest("button[data-confirm]");
  if (btn && !window.confirm(btn.getAttribute("data-confirm"))) { e.preventDefault(); return; }

  var sheet = document.getElementById("sheet");
  if (sheet && e.target.closest("[data-sheet-open]")) {
    sheet.hidden = false; document.body.classList.add("no-scroll");
  } else if (sheet && e.target.closest("[data-sheet-close]")) {
    sheet.hidden = true; document.body.classList.remove("no-scroll");
  }

  var dismiss = e.target.closest("[data-dismiss]");
  if (dismiss) { dismiss.parentElement.remove(); }
});
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) { e.preventDefault(); }
});
document.addEventListener("keydown", function (e) {
  var sheet = document.getElementById("sheet");
  if (e.key === "Escape" && sheet && !sheet.hidden) { sheet.hidden = true; document.body.classList.remove("no-scroll"); }
});
