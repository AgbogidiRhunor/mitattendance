// Selection helper for the usher screen. Selections are temporary and apply to the
// current page only; nothing is saved until the server confirms the POST.
(function () {
  var form = document.getElementById("attendance-form");
  if (!form) { return; }
  var picks = Array.prototype.slice.call(form.querySelectorAll("input.pick"));
  var all = document.getElementById("select-page");
  var counter = document.getElementById("selected-count");
  var save = document.getElementById("save-btn");
  var submitting = false;

  function selected() { return picks.filter(function (c) { return c.checked; }).length; }
  function refresh() {
    var n = selected();
    counter.textContent = n;
    save.disabled = n === 0;
    if (all) {
      all.disabled = picks.length === 0;
      all.checked = picks.length > 0 && n === picks.length;
      all.indeterminate = n > 0 && n < picks.length;
    }
  }
  picks.forEach(function (c) { c.addEventListener("change", refresh); });
  if (all) {
    all.addEventListener("change", function () {
      picks.forEach(function (c) { c.checked = all.checked; });
      refresh();
    });
  }
  form.addEventListener("submit", function (e) {
    var n = selected();
    if (n === 0) { e.preventDefault(); return; }
    if (!window.confirm("Save attendance for " + n + " " + (n === 1 ? "person" : "people") +
        "? Saved attendance cannot be undone by ushers.")) { e.preventDefault(); return; }
    submitting = true;
    save.disabled = true;
    save.textContent = "Saving…";
  });
  // Warn before leaving the page with unsaved selections.
  window.addEventListener("beforeunload", function (e) {
    if (!submitting && selected() > 0) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("pageshow", refresh); // restores state after back/forward cache
  refresh();
})();
