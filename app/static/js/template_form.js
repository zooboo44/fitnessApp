(function () {
  "use strict";

  const data = JSON.parse(document.getElementById("tpl-data").textContent || "{}");
  const cfg = JSON.parse(document.getElementById("tpl-config").textContent);
  const state = {
    name: data.name || "",
    notes: data.notes || "",
    exercises: (data.exercises || []).map((ex) => ({ name: ex.name, sets: ex.sets.map((s) => ({ ...s })) })),
  };

  const listEl = document.getElementById("tpl-exercises");
  const nameEl = document.getElementById("tpl-name");
  const notesEl = document.getElementById("tpl-notes");
  nameEl.value = state.name;
  notesEl.value = state.notes;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c instanceof Node ? c : String(c));
    return node;
  }

  const val = (v) => (v === null || v === undefined ? "" : v);

  function newSet(ex) {
    const last = ex.sets[ex.sets.length - 1];
    return last ? { ...last } : { reps: 10, weight: null, rest_seconds: cfg.defaultRest };
  }

  function render() {
    listEl.replaceChildren();
    if (!state.exercises.length) {
      listEl.append(el("p", { class: "muted" }, "No exercises yet — add one below."));
    }
    state.exercises.forEach((ex, idx) => listEl.append(renderExercise(ex, idx)));
  }

  function renderExercise(ex, idx) {
    const tbody = el("tbody");
    ex.sets.forEach((s, i) => {
      tbody.append(el("tr", {},
        el("td", { class: "set-num" }, i + 1),
        el("td", {}, el("input", { type: "number", min: 0, step: "any", inputmode: "decimal", value: val(s.weight),
          placeholder: "last", "aria-label": `Set ${i + 1} weight`, oninput: (e) => { s.weight = e.target.value; } })),
        el("td", {}, el("input", { type: "number", min: 0, step: 1, inputmode: "numeric", value: val(s.reps),
          "aria-label": `Set ${i + 1} reps`, oninput: (e) => { s.reps = e.target.value; } })),
        el("td", {}, el("input", { type: "number", min: 0, max: 3600, step: 5, inputmode: "numeric", value: val(s.rest_seconds),
          "aria-label": `Rest after set ${i + 1} (seconds)`, oninput: (e) => { s.rest_seconds = e.target.value; } })),
        el("td", {}, el("button", { type: "button", class: "icon-btn danger", title: "Delete set",
          onclick: () => { ex.sets.splice(i, 1); render(); } }, "✕")),
      ));
    });

    return el("div", { class: "card exercise" },
      el("div", { class: "exercise-head" },
        el("input", { type: "text", class: "exercise-name-input", list: "exercise-names", value: ex.name,
          "aria-label": "Exercise", oninput: (e) => { ex.name = e.target.value; } }),
        el("div", { class: "tpl-row-tools" },
          el("button", { type: "button", class: "icon-btn", title: "Move up", disabled: idx === 0,
            onclick: () => { swap(idx, idx - 1); } }, "↑"),
          el("button", { type: "button", class: "icon-btn", title: "Move down", disabled: idx === state.exercises.length - 1,
            onclick: () => { swap(idx, idx + 1); } }, "↓"),
          el("button", { type: "button", class: "icon-btn danger", title: "Remove exercise",
            onclick: () => { state.exercises.splice(idx, 1); render(); } }, "✕"),
        ),
      ),
      el("table", { class: "sets live tpl-sets" },
        el("thead", {}, el("tr", {},
          el("th", {}, "#"), el("th", {}, cfg.unit), el("th", {}, "Reps"), el("th", {}, "Rest (s)"), el("th", {}, ""),
        )),
        tbody,
      ),
      el("button", { type: "button", class: "btn btn-block btn-ghost",
        onclick: () => { ex.sets.push(newSet(ex)); render(); } }, "+ Add set"),
    );
  }

  function swap(i, j) {
    [state.exercises[i], state.exercises[j]] = [state.exercises[j], state.exercises[i]];
    render();
  }

  function addExercise() {
    const input = document.getElementById("tpl-add-name");
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    state.exercises.push({ name, sets: [{ reps: 10, weight: null, rest_seconds: cfg.defaultRest }] });
    input.value = "";
    render();
  }
  document.getElementById("tpl-add").addEventListener("click", addExercise);
  document.getElementById("tpl-add-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addExercise(); }
  });

  document.getElementById("template-form").addEventListener("submit", () => {
    state.name = nameEl.value;
    state.notes = notesEl.value;
    document.getElementById("payload").value = JSON.stringify(state);
  });

  render();
})();
