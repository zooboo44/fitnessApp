(function () {
  "use strict";

  const root = document.getElementById("workout");
  const workoutId = root.dataset.workoutId;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const listEl = document.getElementById("exercises");
  const REST_STEP = 15;
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
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = msg;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3500);
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

  function findSet(setId) {
    for (const we of state.exercises) {
      const s = we.sets.find((x) => x.id === setId);
      if (s) return { we, s };
    }
    return null;
  }

  // ------------------------------------------------------------------ rendering

  // setId -> the <tr> holding that set's rest timer, so the timer can update it in place.
  const timerRows = new Map();

  function render() {
    timerRows.clear();
    listEl.replaceChildren();
    if (!state.exercises.length) {
      listEl.append(el("p", { class: "muted" }, "No exercises yet — add one below."));
      return;
    }
    state.exercises.forEach((we, idx) => listEl.append(renderExercise(we, idx)));
  }

  function renderExercise(we, idx) {
    const tbody = el("tbody");
    we.sets.forEach((s, i) => {
      tbody.append(renderSet(we, s, i));
      const tr = renderTimerRow(we, s);
      timerRows.set(s.id, tr);
      tbody.append(tr);
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
      el("table", { class: "sets live" },
        el("thead", {}, el("tr", {},
          el("th", {}, "#"), el("th", {}, "Prev"), el("th", {}, state.unit),
          el("th", {}, "Reps"), el("th", {}, "Done"), el("th", {}, ""),
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

    const row = el("tr", { class: "set-row" + (s.completed ? " done" : "") },
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
        "aria-label": `Set ${i + 1} done`, title: "Done with this set",
        onclick: () => toggleSet(we, s, row, weight, reps),
      }, "✓")),
      el("td", {}, el("button", { type: "button", class: "icon-btn danger", title: "Delete set", onclick: () => removeSet(we, s) }, "✕")),
    );
    return row;
  }

  // The rest timer shown under each set. States: waiting (set not done yet),
  // running (counting down), rested (set done, timer finished or skipped).
  function renderTimerRow(we, s) {
    const isRunning = timer.runningSetId() === s.id;
    const status = isRunning ? "running" : s.completed ? "rested" : "waiting";
    const cell = el("td", { colspan: 6 });
    const box = el("div", { class: `set-timer ${status}` });
    cell.append(box);

    if (isRunning) {
      box.append(
        el("div", { class: "set-timer-fill" }),
        el("button", { type: "button", class: "timer-btn", "aria-label": `Rest ${REST_STEP} seconds less`, onclick: () => timer.adjust(-REST_STEP) }, `−${REST_STEP}`),
        el("span", { class: "set-timer-label" }, "Resting ", el("strong", { class: "set-timer-time" }, "")),
        el("button", { type: "button", class: "timer-btn", "aria-label": `Rest ${REST_STEP} seconds more`, onclick: () => timer.adjust(REST_STEP) }, `+${REST_STEP}`),
        el("button", { type: "button", class: "timer-btn primary", onclick: () => timer.stop() }, "Skip"),
      );
    } else {
      const setRest = (secs) => {
        s.rest_seconds = Math.max(0, Math.min(Duration.MAX, secs));
        refreshTimerRow(s.id);
        debounced(`set-${s.id}-rest_seconds`, () => api("PATCH", `/api/sets/${s.id}`, { rest_seconds: s.rest_seconds }));
      };
      // Type a rest time (90, 1:30, 2m, 1m30s) or nudge it with the buttons.
      const input = el("input", {
        type: "text", class: "rest-time-input", value: Duration.format(s.rest_seconds),
        autocomplete: "off", enterkeyhint: "done", "aria-label": "Rest time (e.g. 90 or 1:30)",
        title: "Type a rest time, e.g. 90, 1:30 or 2m",
        onfocus: (e) => e.target.select(),
        onkeydown: (e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { e.target.value = Duration.format(s.rest_seconds); e.target.blur(); } },
        onchange: (e) => {
          const secs = Duration.parse(e.target.value);
          if (secs === null) {
            toast("Couldn't read that rest time — try 90, 1:30 or 2m.");
            e.target.value = Duration.format(s.rest_seconds);
            return;
          }
          setRest(secs);
        },
      });
      box.append(
        el("button", { type: "button", class: "timer-btn", "aria-label": `Rest ${REST_STEP} seconds less`, disabled: s.rest_seconds <= 0, onclick: () => setRest((s.rest_seconds || 0) - REST_STEP) }, `−${REST_STEP}`),
        el("span", { class: "set-timer-label" },
          status === "rested" ? "✓ Rested " : "Rest ", input,
          status === "waiting" && s.rest_seconds > 0 ? el("span", { class: "muted hint" }, " · starts when set is done") : null,
          s.rest_seconds <= 0 ? el("span", { class: "muted hint" }, " · no timer") : null),
        el("button", { type: "button", class: "timer-btn", "aria-label": `Rest ${REST_STEP} seconds more`, onclick: () => setRest((s.rest_seconds || 0) + REST_STEP) }, `+${REST_STEP}`),
      );
    }
    return el("tr", { class: "timer-row" }, cell);
  }

  function refreshTimerRow(setId) {
    const old = timerRows.get(setId);
    const found = findSet(setId);
    if (!old || !found) return;
    const tr = renderTimerRow(found.we, found.s);
    old.replaceWith(tr);
    timerRows.set(setId, tr);
    timer.rowReplaced(setId);
    timer.paint();
  }

  // ------------------------------------------------------------------ actions

  async function toggleSet(we, s, row, weightInput, repsInput) {
    unlockAudio();
    const completing = !s.completed;
    const body = { completed: completing };
    // Ticking a set without typing anything uses the placeholder (previous workout) values.
    if (completing) {
      if (s.weight === null && weightInput.placeholder) { s.weight = Number(weightInput.placeholder); weightInput.value = weightInput.placeholder; body.weight = s.weight; }
      if (s.reps === null && repsInput.placeholder) { s.reps = Number(repsInput.placeholder); repsInput.value = repsInput.placeholder; body.reps = s.reps; }
    }
    // Send any queued edits to this set with the same request.
    for (const f of ["weight", "reps", "rest_seconds"]) {
      const k = `set-${s.id}-${f}`;
      if (pending.has(k)) { clearTimeout(pending.get(k)); pending.delete(k); body[f] = s[f]; }
    }
    const setChecked = (on) => {
      s.completed = on;
      row.classList.toggle("done", on);
      const btn = row.querySelector(".check");
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", String(on));
    };
    setChecked(completing);
    try {
      await api("PATCH", `/api/sets/${s.id}`, body);
    } catch (_) {
      setChecked(!completing);
      return;
    }
    if (completing && s.rest_seconds > 0) {
      timer.start(s.id, s.rest_seconds);
    } else {
      if (timer.runningSetId() === s.id) timer.stop();
      refreshTimerRow(s.id);
    }
  }

  async function addSet(we) {
    const s = await api("POST", `/api/workout-exercises/${we.id}/sets`);
    we.sets.push(s);
    render();
    timer.reobserve();
    timer.paint();
  }

  async function removeSet(we, s) {
    await api("DELETE", `/api/sets/${s.id}`);
    if (timer.runningSetId() === s.id) timer.stop();
    we.sets = we.sets.filter((x) => x.id !== s.id);
    render();
    timer.reobserve();
    timer.paint();
  }

  async function removeExercise(we) {
    if (!confirm(`Remove ${we.name} from this workout?`)) return;
    await api("DELETE", `/api/workout-exercises/${we.id}`);
    if (we.sets.some((s) => s.id === timer.runningSetId())) timer.stop();
    state.exercises = state.exercises.filter((x) => x.id !== we.id);
    render();
    timer.reobserve();
    timer.paint();
  }

  async function move(we, dir) {
    await api("PATCH", `/api/workout-exercises/${we.id}`, { move: dir });
    const i = state.exercises.indexOf(we);
    const j = dir === "up" ? i - 1 : i + 1;
    [state.exercises[i], state.exercises[j]] = [state.exercises[j], state.exercises[i]];
    render();
    timer.reobserve();
    timer.paint();
  }

  document.getElementById("add-exercise").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("add-exercise-name");
    const name = input.value.trim();
    if (!name) return;
    const we = await api("POST", `/api/workouts/${workoutId}/exercises`, { name, sets: 1 });
    state.exercises.push(we);
    input.value = "";
    render();
    timer.reobserve();
    timer.paint();
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
  document.querySelectorAll(".finish-form").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      // form.submit() drops the clicked button's value, so copy the choice into the form.
      const choice = form.querySelector('input[name="template_update"]');
      if (choice && e.submitter && e.submitter.value) choice.value = e.submitter.value;
      form.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      await flushPending();
      timer.stop();
      form.submit();
    });
  });

  const finishDialog = document.getElementById("finish-dialog");
  if (finishDialog) {
    document.getElementById("finish-open").addEventListener("click", () => finishDialog.showModal());
    document.getElementById("finish-cancel").addEventListener("click", () => finishDialog.close());
    finishDialog.addEventListener("click", (e) => { if (e.target === finishDialog) finishDialog.close(); });
  }

  async function flushPending() {
    const calls = [];
    for (const [key, handle] of pending) {
      clearTimeout(handle);
      pending.delete(key);
      if (key.startsWith("set-")) {
        const [, id, field] = key.match(/^set-(\d+)-(\w+)$/) || [];
        const found = id && findSet(Number(id));
        if (found) calls.push(api("PATCH", `/api/sets/${id}`, { [field]: found.s[field] }));
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

  // One rest timer runs at a time. It is drawn inline under its set and mirrored in a
  // bar pinned to the bottom of the screen (so it's visible while scrolling).
  const timer = (() => {
    const bar = document.getElementById("rest-timer");
    const barTime = document.getElementById("rest-time");
    const barLabel = document.getElementById("rest-label");
    const barFill = document.getElementById("rest-bar");
    const storageKey = `rest-timer-${workoutId}`;
    let current = null; // { setId, endAt, total }
    let handle = null;
    let rowVisible = false;
    let finishedFlash = false;

    // The bottom bar only shows while the running timer row is scrolled out of view
    // (or briefly when a rest finishes).
    const observer = "IntersectionObserver" in window
      ? new IntersectionObserver((entries) => {
          rowVisible = entries.some((e) => e.isIntersecting);
          syncBar();
        }, { rootMargin: "0px 0px -110px 0px" })
      : null;

    function observeRow() {
      if (!observer) return;
      observer.disconnect();
      rowVisible = false;
      const row = current && timerRows.get(current.setId);
      if (row) observer.observe(row);
    }

    function syncBar() {
      const show = finishedFlash || (current && !rowVisible);
      bar.hidden = !show;
      document.body.classList.toggle("has-rest-timer", !!show);
    }

    function persist() {
      try {
        if (current) localStorage.setItem(storageKey, JSON.stringify(current));
        else localStorage.removeItem(storageKey);
      } catch (_) { /* storage unavailable */ }
    }

    function paint() {
      if (!current) return;
      const left = (current.endAt - Date.now()) / 1000;
      if (left <= 0) { finish(); return; }
      const pct = `${Math.max(0, Math.min(100, (left / current.total) * 100))}%`;
      const text = fmtClock(Math.ceil(left));
      barTime.textContent = text;
      barFill.style.width = pct;
      const row = timerRows.get(current.setId);
      if (row) {
        const t = row.querySelector(".set-timer-time");
        const f = row.querySelector(".set-timer-fill");
        if (t) t.textContent = text;
        if (f) f.style.width = pct;
      }
    }

    function labelFor(setId) {
      const found = findSet(setId);
      if (!found) return "Rest";
      return `Rest after ${found.we.name} · set ${found.we.sets.indexOf(found.s) + 1}`;
    }

    function showBar() {
      finishedFlash = false;
      bar.classList.remove("finished");
      syncBar();
    }

    function hideBar() {
      finishedFlash = false;
      syncBar();
    }

    function clear() {
      const setId = current ? current.setId : null;
      clearInterval(handle);
      current = null;
      persist();
      if (observer) observer.disconnect();
      if (setId !== null) refreshTimerRow(setId);
    }

    function finish() {
      clear();
      barTime.textContent = "Go!";
      barFill.style.width = "0%";
      bar.classList.add("finished");
      finishedFlash = true;
      syncBar();
      beep();
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      setTimeout(() => { if (!current) hideBar(); }, 4000);
    }

    function run() {
      barLabel.textContent = labelFor(current.setId);
      showBar();
      clearInterval(handle);
      handle = setInterval(paint, 250);
      refreshTimerRow(current.setId);
      paint();
    }

    function rowReplaced(setId) {
      if (current && current.setId === setId) observeRow();
    }

    return {
      runningSetId: () => (current ? current.setId : null),
      paint,
      rowReplaced,
      reobserve: observeRow,
      start(setId, seconds) {
        const previous = current ? current.setId : null;
        current = { setId, endAt: Date.now() + seconds * 1000, total: seconds };
        persist();
        if (previous !== null && previous !== setId) refreshTimerRow(previous);
        run();
      },
      adjust(delta) {
        if (!current) return;
        current.endAt += delta * 1000;
        current.total = Math.max(current.total + delta, 1);
        persist();
        paint();
      },
      stop() {
        clear();
        hideBar();
      },
      restore() {
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
          if (saved && saved.endAt > Date.now() && findSet(saved.setId)) {
            current = saved;
            run();
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
