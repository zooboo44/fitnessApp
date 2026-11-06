// Parsing/formatting for rest times typed by the user. Shared by the workout screen
// and the template editor.
window.Duration = (function () {
  "use strict";
  const MAX = 3600;

  // "90" -> 90, "1:30" -> 90, "2m" -> 120, "1m30s" -> 90, "1.5m" -> 90, "45s" -> 45.
  // Returns null when the text can't be understood.
  function parse(text) {
    const s = String(text ?? "").trim().toLowerCase().replace(/\s+/g, "");
    if (!s) return null;
    let secs = null;
    let m;
    if ((m = s.match(/^(\d+):(\d{1,2})$/))) {
      if (Number(m[2]) >= 60) return null;
      secs = Number(m[1]) * 60 + Number(m[2]);
    } else if ((m = s.match(/^(\d+)(?:s|sec|secs|seconds?)?$/))) {
      secs = Number(m[1]);
    } else if ((m = s.match(/^(\d+(?:\.\d+)?)(?:m|min|mins|minutes?)$/))) {
      secs = Math.round(Number(m[1]) * 60);
    } else if ((m = s.match(/^(\d+)(?:m|min)(\d+)(?:s|sec)?$/))) {
      secs = Number(m[1]) * 60 + Number(m[2]);
    }
    if (secs === null || !Number.isFinite(secs)) return null;
    return Math.max(0, Math.min(MAX, secs));
  }

  function format(totalSeconds) {
    totalSeconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  return { parse, format, MAX };
})();
