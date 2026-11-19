/* Synthesis route page (templates/synthesis.html).
 *
 * Loads a material's steps into the table, and adds, edits and deletes them through
 * /api/materials/{id}/synthesis and /api/synthesis/{step_id} (routers/synthesis.py).
 * Rows are built with textContent, never innerHTML, so typed text is shown as text.
 */
(function () {
    "use strict";

    const root = document.getElementById("synthesis");
    if (!root) return;

    const materialId = root.dataset.materialId;
    const listUrl = "/api/materials/" + encodeURIComponent(materialId) + "/synthesis";
    // Form field names, and the table's columns in the same order
    const FIELDS = ["step_no", "step_type", "temperature_c", "duration_h", "atmosphere",
                    "equipment", "performed_by", "performed_on", "notes"];
    const CELL_STYLE = "padding: 8px; border-bottom: 1px solid #eee; vertical-align: top;";
    const SMALL_BUTTON = "margin: 0 4px 0 0; padding: 4px 10px; font-size: 12px;";

    const tbody = root.querySelector("[data-steps]");
    const empty = root.querySelector("[data-empty]");
    const form = root.querySelector("[data-step-form]");
    const title = root.querySelector("[data-form-title]");
    const cancel = root.querySelector("[data-cancel]");
    const errorLine = root.querySelector("[data-error]");
    const successLine = root.querySelector("[data-success]");

    let editingId = null;  // step_id being edited, or null when adding

    function show(line, text) {
        errorLine.hidden = true;
        successLine.hidden = true;
        if (!line) return;
        line.textContent = text;
        line.hidden = false;
    }

    // --- Talking to the API --------------------------------------------------

    async function call(method, url, body) {
        const options = {method: method, headers: {"Accept": "application/json"}};
        if (body !== undefined) {
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
        const res = await fetch(url, options);
        if (res.status === 401 || (res.redirected && res.url.endsWith("/login"))) {
            throw new Error("Please log in again.");
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || "Something went wrong (" + res.status + ").");
        }
        return data;
    }

    // --- Table ---------------------------------------------------------------

    function cell(text) {
        const td = document.createElement("td");
        td.setAttribute("style", CELL_STYLE);
        td.textContent = text === null || text === undefined || text === "" ? "—" : String(text);
        return td;
    }

    function smallButton(label, background, onClick) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.setAttribute("style", SMALL_BUTTON + (background ? " background: " + background + ";" : ""));
        button.addEventListener("click", onClick);
        return button;
    }

    function row(step) {
        const tr = document.createElement("tr");
        for (const field of FIELDS) {
            tr.appendChild(cell(step[field]));
        }
        const actions = document.createElement("td");
        actions.setAttribute("style", CELL_STYLE + " white-space: nowrap;");
        actions.appendChild(smallButton("Edit", null, () => startEdit(step)));
        actions.appendChild(smallButton("Delete", "#c62828", () => remove(step)));
        tr.appendChild(actions);
        return tr;
    }

    async function load() {
        try {
            const data = await call("GET", listUrl);
            tbody.replaceChildren();
            for (const step of data.steps) {
                tbody.appendChild(row(step));
            }
            empty.hidden = data.steps.length > 0;
        } catch (err) {
            show(errorLine, err.message);
        }
    }

    // --- Form ----------------------------------------------------------------

    function resetForm() {
        form.reset();
        form.elements.performed_by.value = root.dataset.performedBy || "";
        editingId = null;
        title.textContent = "Add a step";
        cancel.hidden = true;
    }

    function startEdit(step) {
        for (const field of FIELDS) {
            const value = step[field];
            form.elements[field].value = value === null || value === undefined ? "" : value;
        }
        editingId = step.step_id;
        title.textContent = "Edit step " + step.step_no;
        cancel.hidden = false;
        show(null);
        form.scrollIntoView({behavior: "smooth"});
    }

    async function save(event) {
        event.preventDefault();
        const values = {};
        for (const field of FIELDS) {
            values[field] = form.elements[field].value;
        }
        try {
            if (editingId === null) {
                await call("POST", listUrl, values);
                show(successLine, "Step added.");
            } else {
                await call("PUT", "/api/synthesis/" + editingId, values);
                show(successLine, "Step saved.");
            }
            resetForm();
            await load();
        } catch (err) {
            show(errorLine, err.message);
        }
    }

    async function remove(step) {
        if (!confirm("Delete step " + step.step_no + " (" + step.step_type + ")?")) return;
        try {
            await call("DELETE", "/api/synthesis/" + step.step_id);
            if (editingId === step.step_id) resetForm();
            show(successLine, "Step deleted.");
            await load();
        } catch (err) {
            show(errorLine, err.message);
        }
    }

    form.addEventListener("submit", save);
    cancel.addEventListener("click", () => {
        resetForm();
        show(null);
    });

    resetForm();
    load();
})();
