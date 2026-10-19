// Runs before first paint to avoid a flash of the wrong theme. External file: the CSP forbids inline scripts.
try {
  var t = localStorage.getItem("aidap-theme");
  if (!t) t = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = t;
} catch (e) { /* storage unavailable: keep the default */ }
