(function () {
  "use strict";

  const root = document.getElementById("workout");
  const workoutId = root.dataset.workoutId;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const listEl = document.getElementById("exercises");
  let state = null;

  // ------------------------------------------------------------------ API helpers

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      keepalive: true, // lets edits flushed during page unload still reach the server
    });
    if (res.status === 401) {
      window.location = "/auth/login";
      throw new Error("not signed in");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast(data.error || "Something went wrong — please retry.");
      throw new Error(data.error || res.statusText);
    }
    return data;
  }

  const pending = new Map();
  function debounced(key, fn, ms = 500) {
    clearTimeout(pending.get(key));
    pending.set(key, setTimeout(() => { pending.delete(key); fn(); }, ms));
  }

  function toast(msg) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ------------------------------------------------------------------ helpers

  function fmtClock(totalSeconds) {
    totalSeconds = Math.max(0, Math.round(totalSeconds));
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const ss = String(s).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  }

  function fmtWeight(w) {
    if (w === null || w === undefined || w === "") return "";
    return String(Math.round(Number(w) * 100) / 100);
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const c of children) {
      if (c === null || c === undefined) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  // ------------------------------------------------------------------ rendering

  function render() {
    listEl.replaceChildren();
    if (!state.exercises.length) {
      listEl.append(el("p", { class: "muted" }, "No exercises yet — add one below."));
      return;
    }
    state.exercises.forEach((we, idx) => listEl.append(renderExercise(we, idx)));
  }

  function renderExercise(we, idx) {
    const tbody = el("tbody");
    we.sets.forEach((s, i) => tbody.append(renderSet(we, s, i)));

    const restInput = el("input", {
      type: "number", min: 0, max: 3600, step: 5, value: we.rest_seconds,
      class: "rest-input", inputmode: "numeric", "aria-label": "Rest seconds",
      oninput: (e) => {
        we.rest_seconds = parseInt(e.target.value || "0", 10) || 0;
        debounced(`we-${we.id}`, () => api("PATCH", `/api/workout-exercises/${we.id}`, { rest_seconds: we.rest_seconds }));
      },
    });

    return el("div", { class: "card exercise" },
      el("div", { class: "exercise-head" },
        el("h3", {}, we.name),
        el("div", { class: "tpl-row-tools" },
          el("button", { type: "button", class: "icon-btn", title: "Move up", disabled: idx === 0, onclick: () => move(we, "up") }, "↑"),
          el("button", { type: "button", class: "icon-btn", title: "Move down", disabled: idx === state.exercises.length - 1, onclick: () => move(we, "down") }, "↓"),
          el("button", { type: "button", class: "icon-btn danger", title: "Remove exercise", onclick: () => removeExercise(we) }, "✕"),
        ),
      ),
      el("label", { class: "rest-setting small muted" }, "Rest timer ", restInput, " s"),
      el("table", { class: "sets live" },
        el("thead", {}, el("tr", {},
          el("th", {}, "#"), el("th", {}, "Prev"), el("th", {}, state.unit),
          el("th", {}, "Reps"), el("th", {}, "✓"), el("th", {}, ""),
        )),
        tbody,
      ),
      el("button", { type: "button", class: "btn btn-block btn-ghost", onclick: () => addSet(we) }, "+ Add set"),
    );
  }

  function renderSet(we, s, i) {
    const prev = we.previous[i] || null;
    const prevText = prev && (prev.weight !== null || prev.reps !== null)
      ? `${fmtWeight(prev.weight) || "–"} × ${prev.reps ?? "–"}` : "–";

    const save = (field, value) => {
      s[field] = value === "" ? null : value;
      debounced(`set-${s.id}-${field}`, () => api("PATCH", `/api/sets/${s.id}`, { [field]: s[field] }));
    };

    const weight = el("input", {
      type: "number", min: 0, step: "any", inputmode: "decimal", value: fmtWeight(s.weight),
      placeholder: prev ? fmtWeight(prev.weight) : "", "aria-label": `Set ${i + 1} weight`,
      oninput: (e) => save("weight", e.target.value),
    });
    const reps = el("input", {
      type: "number", min: 0, step: 1, inputmode: "numeric", value: s.reps ?? "",
      placeholder: prev && prev.reps !== null ? prev.reps : "", "aria-label": `Set ${i + 1} reps`,
      oninput: (e) => save("reps", e.target.value),
    });

    const row = el("tr", { class: s.completed ? "done" : "" },
      el("td", { class: "set-num" }, i + 1),
      el("td", { class: "muted small prev", title: "Tap to copy", onclick: () => {
        if (!prev) return;
        weight.value = fmtWeight(prev.weight); save("weight", weight.value);
        reps.value = prev.reps ?? ""; save("reps", reps.value);
      } }, prevText),
      el("td", {}, weight),
      el("td", {}, reps),
      el("td", {}, el("button", {
        type: "button", class: "check" + (s.completed ? " on" : ""), "aria-pressed": String(s.completed),
        "aria-label": `Mark set ${i + 1} complete`,
        onclick: () => toggleSet(we, s, row, weight, reps),
      }, "✓")),
      el("td", {}, el("button", { type: "button", class: "icon-btn danger", title: "Delete set", onclick: () => removeSet(we, s) }, "✕")),
    );
    return row;
  }

  // ------------------------------------------------------------------ actions

  async function toggleSet(we, s, row, weightInput, repsInput) {
    unlockAudio();
    const completing = !s.completed;
    const body = { completed: completing };
    // If the user ticks a set without typing anything, fill from placeholders (previous values).
    if (completing) {
      if (s.weight === null && weightInput.placeholder) { s.weight = Number(weightInput.placeholder); weightInput.value = weightInput.placeholder; body.weight = s.weight; }
      if (s.reps === null && repsInput.placeholder) { s.reps = Number(repsInput.placeholder); repsInput.value = repsInput.placeholder; body.reps = s.reps; }
      // Make sure any queued edits to this set go out with the same request.
      for (const f of ["weight", "reps"]) {
        const k = `set-${s.id}-${f}`;
        if (pending.has(k)) { clearTimeout(pending.get(k)); pending.delete(k); body[f] = s[f]; }
      }
    }
    s.completed = completing;
    row.classList.toggle("done", completing);
    const btn = row.querySelector(".check");
    btn.classList.toggle("on", completing);
    btn.setAttribute("aria-pressed", String(completing));
    try {
      await api("PATCH", `/api/sets/${s.id}`, body);
    } catch (_) {
      s.completed = !completing;
      row.classList.toggle("done", !completing);
      btn.classList.toggle("on", !completing);
      return;
    }
    if (completing && we.rest_seconds > 0) {
      timer.start(we.rest_seconds, `Rest after ${we.name}`);
    }
  }

  async function addSet(we) {
    const s = await api("POST", `/api/workout-exercises/${we.id}/sets`);
    we.sets.push(s);
    render();
  }

  async function removeSet(we, s) {
    await api("DELETE", `/api/sets/${s.id}`);
    we.sets = we.sets.filter((x) => x.id !== s.id);
    render();
  }

  async function removeExercise(we) {
    if (!confirm(`Remove ${we.name} from this workout?`)) return;
    await api("DELETE", `/api/workout-exercises/${we.id}`);
    state.exercises = state.exercises.filter((x) => x.id !== we.id);
    render();
  }

  async function move(we, dir) {
    await api("PATCH", `/api/workout-exercises/${we.id}`, { move: dir });
    const i = state.exercises.indexOf(we);
    const j = dir === "up" ? i - 1 : i + 1;
    [state.exercises[i], state.exercises[j]] = [state.exercises[j], state.exercises[i]];
    render();
  }

  document.getElementById("add-exercise").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("add-exercise-name");
    const name = input.value.trim();
    if (!name) return;
    const we = await api("POST", `/api/workouts/${workoutId}/exercises`, { name, sets: 3 });
    state.exercises.push(we);
    input.value = "";
    render();
    const dl = document.getElementById("exercise-names");
    if (![...dl.options].some((o) => o.value.toLowerCase() === we.name.toLowerCase())) {
      dl.append(el("option", { value: we.name }));
    }
  });

  document.getElementById("workout-name").addEventListener("input", (e) => {
    debounced("name", () => api("PATCH", `/api/workouts/${workoutId}`, { name: e.target.value }), 700);
  });
  document.getElementById("workout-notes").addEventListener("input", (e) => {
    debounced("notes", () => api("PATCH", `/api/workouts/${workoutId}`, { notes: e.target.value }), 700);
  });

  // Flush pending edits before finishing so nothing typed is lost.
  document.getElementById("finish-form").addEventListener("submit", async (e) => {
    if (!pending.size) {
      timer.stop();
      return;
    }
    e.preventDefault();
    await flushPending();
    timer.stop();
    e.target.submit();
  });

  async function flushPending() {
    // Each pending entry is a timeout wrapping an API call; trigger them all now.
    const calls = [];
    for (const [key, handle] of pending) {
      clearTimeout(handle);
      pending.delete(key);
      if (key.startsWith("set-")) {
        const [, id, field] = key.split("-");
        const s = state.exercises.flatMap((we) => we.sets).find((x) => String(x.id) === id);
        if (s) calls.push(api("PATCH", `/api/sets/${id}`, { [field]: s[field] }));
      } else if (key.startsWith("we-")) {
        const we = state.exercises.find((x) => `we-${x.id}` === key);
        if (we) calls.push(api("PATCH", `/api/workout-exercises/${we.id}`, { rest_seconds: we.rest_seconds }));
      } else if (key === "name" || key === "notes") {
        const v = document.getElementById(`workout-${key}`).value;
        calls.push(api("PATCH", `/api/workouts/${workoutId}`, { [key]: v }));
      }
    }
    await Promise.allSettled(calls);
  }

  window.addEventListener("pagehide", () => { if (pending.size) flushPending(); });

  // ------------------------------------------------------------------ elapsed clock

  function startElapsedClock() {
    const started = new Date(state.started_at).getTime();
    const out = document.getElementById("elapsed");
    const tick = () => { out.textContent = fmtClock((Date.now() - started) / 1000); };
    tick();
    setInterval(tick, 1000);
  }

  // ------------------------------------------------------------------ rest timer

  let audioCtx = null;
  function unlockAudio() {
    // Browsers only allow audio after a user gesture; create the context on first tap.
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
    } catch (_) { /* audio unsupported */ }
  }
  function beep() {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime;
    [0, 0.25, 0.5].forEach((offset, i) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = i === 2 ? 1320 : 880;
      gain.gain.setValueAtTime(0.0001, t0 + offset);
      gain.gain.exponentialRampToValueAtTime(0.3, t0 + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + offset + 0.18);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t0 + offset);
      osc.stop(t0 + offset + 0.2);
    });
  }

  const timer = (() => {
    const box = document.getElementById("rest-timer");
    const timeEl = document.getElementById("rest-time");
    const labelEl = document.getElementById("rest-label");
    const bar = document.getElementById("rest-bar");
    const storageKey = `rest-timer-${workoutId}`;
    let endAt = 0, total = 0, handle = null;

    function persist() {
      try {
        if (endAt) localStorage.setItem(storageKey, JSON.stringify({ endAt, total, label: labelEl.textContent }));
        else localStorage.removeItem(storageKey);
      } catch (_) { /* storage unavailable */ }
    }

    function tick() {
      const left = (endAt - Date.now()) / 1000;
      if (left <= 0) {
        done();
        return;
      }
      timeEl.textContent = fmtClock(Math.ceil(left));
      bar.style.width = `${Math.max(0, Math.min(100, (left / total) * 100))}%`;
    }

    function show() {
      box.hidden = false;
      box.classList.remove("finished");
      document.body.classList.add("has-rest-timer");
      clearInterval(handle);
      handle = setInterval(tick, 250);
      tick();
    }

    function done() {
      clearInterval(handle);
      endAt = 0;
      persist();
      timeEl.textContent = "Go!";
      bar.style.width = "0%";
      box.classList.add("finished");
      beep();
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      setTimeout(() => { if (!endAt) hide(); }, 4000);
    }

    function hide() {
      box.hidden = true;
      document.body.classList.remove("has-rest-timer");
    }

    return {
      start(seconds, label = "Rest") {
        total = seconds;
        endAt = Date.now() + seconds * 1000;
        labelEl.textContent = label;
        persist();
        show();
      },
      adjust(delta) {
        if (!endAt) return;
        endAt += delta * 1000;
        total = Math.max(total + delta, 1);
        persist();
        tick();
      },
      stop() {
        clearInterval(handle);
        endAt = 0;
        persist();
        hide();
      },
      restore() {
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
          if (saved && saved.endAt > Date.now()) {
            endAt = saved.endAt; total = saved.total; labelEl.textContent = saved.label || "Rest";
            show();
          } else {
            localStorage.removeItem(storageKey);
          }
        } catch (_) { /* ignore */ }
      },
    };
  })();

  document.getElementById("rest-timer").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-rest]");
    if (!b) return;
    unlockAudio();
    if (b.dataset.rest === "skip") timer.stop();
    else timer.adjust(parseInt(b.dataset.rest, 10));
  });

  document.getElementById("manual-timer").addEventListener("click", () => {
    unlockAudio();
    const input = prompt("Rest timer length (seconds):", "90");
    const secs = parseInt(input || "", 10);
    if (secs > 0) timer.start(secs, "Rest");
  });

  // Keep the screen awake during a workout where supported.
  async function keepAwake() {
    try {
      if ("wakeLock" in navigator) await navigator.wakeLock.request("screen");
    } catch (_) { /* not critical */ }
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") keepAwake(); });

  // ------------------------------------------------------------------ boot

  api("GET", `/api/workouts/${workoutId}`).then((data) => {
    state = data;
    render();
    startElapsedClock();
    timer.restore();
    keepAwake();
  });
})();
