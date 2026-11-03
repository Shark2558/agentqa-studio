/* Applies the saved Appearance (theme + accent) before the first paint, so a dark-mode person never sees a white
   flash. Plain ES5 on purpose; the same key and lists live in src/lib/theme.ts (a test keeps them in step).
   Loaded from <head> as a separate file because the app's security policy allows no inline scripts. */
(function () {
  var KEY = "agentqa.theme";
  var MODES = ["light", "dark", "system"];
  var ACCENTS = ["blue", "indigo", "teal", "green", "slate"];
  try {
    var raw = window.localStorage.getItem(KEY);
    var data = raw ? JSON.parse(raw) : null;
    var root = document.documentElement;
    var mode = data && MODES.indexOf(data.mode) >= 0 ? data.mode : "system";
    var accent = data && ACCENTS.indexOf(data.accent) >= 0 ? data.accent : "blue";
    if (mode !== "system") root.setAttribute("data-theme", mode);
    root.setAttribute("data-accent", accent);
  } catch (e) {
    /* no storage or bad data: the OS theme and Blue apply */
  }
})();
