(function () {
  const rows = document.getElementById("rows");
  const tpl = document.getElementById("row-template");

  function addRow() {
    const node = tpl.content.firstElementChild.cloneNode(true);
    rows.appendChild(node);
    node.querySelector('input[name="exercise_name"]').focus();
  }

  document.getElementById("add-row").addEventListener("click", addRow);

  rows.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const row = btn.closest(".tpl-row");
    const act = btn.dataset.act;
    if (act === "remove") row.remove();
    if (act === "up" && row.previousElementSibling) rows.insertBefore(row, row.previousElementSibling);
    if (act === "down" && row.nextElementSibling) rows.insertBefore(row.nextElementSibling, row);
  });

  if (!rows.children.length) addRow();
})();
