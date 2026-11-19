// Mixing page (templates/mixing.html): charts, slurry lineage and the model.
//
// Loads /api/mixing/{id} for the chosen run and draws it on the dark canvas in the
// same style as the traceability graph (same neon colours as graph.html).
// Chart.js and vis-network are loaded by base.html.
(function () {
    const COLOUR = {
        material: '#00e5ff', coating: '#7c4dff', slp: '#00ff9d',
        coincell: '#ff6ec7', mlp: '#ffb800', mixing: '#ff8a3d',
    };
    const BORDER = {
        material: '#00b8cc', coating: '#5c35cc', slp: '#00cc7d',
        coincell: '#cc5599', mlp: '#cc9300', mixing: '#cc6e30',
    };
    const GRID = 'rgba(255,255,255,0.08)';
    const TICK = '#9aa6c7';
    const HIGH_RPM = 3000;  // stages at or above this speed are drawn amber

    const app = document.getElementById('mixingApp');
    const charts = {};
    let current = null;     // the run shown: the /api/mixing/{id} reply
    let view = 'trace';
    let network = null;
    let modelResult = null;

    Chart.defaults.color = TICK;
    Chart.defaults.font.family = "-apple-system, 'Segoe UI', Arial, sans-serif";

    // ---- small helpers -----------------------------------------------------------

    function esc(value) {
        return String(value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function num(value, digits, unit) {
        if (value === null || value === undefined) return '—';
        return Number(value).toFixed(digits) + (unit || '');
    }
    function minutes(seconds) {
        return seconds === null || seconds === undefined ? '—'
            : Math.floor(seconds / 60) + ' min ' + String(Math.round(seconds % 60)).padStart(2, '0') + ' s';
    }
    function draw(id, config) {
        if (charts[id]) charts[id].destroy();
        charts[id] = new Chart(document.getElementById(id), config);
        return charts[id];
    }
    function pairs(xs, ys, xScale, yScale) {
        const out = [];
        for (let i = 0; i < xs.length; i++) {
            if (ys[i] !== null && ys[i] !== undefined) out.push({ x: xs[i] * (xScale || 1), y: ys[i] * (yScale || 1) });
        }
        return out;
    }
    const axis = (title, extra) => ({
        title: { display: !!title, text: title, color: TICK },
        grid: { color: GRID }, ticks: { color: TICK }, border: { color: GRID }, ...(extra || {}),
    });
    const legend = { labels: { color: '#e8e8f0', usePointStyle: true, boxWidth: 8 } };

    // ---- views ------------------------------------------------------------------

    // Shades the rotor-on stages behind the trace and numbers them
    const stageBands = {
        id: 'stageBands',
        beforeDatasetsDraw(chart) {
            if (!current) return;
            const { ctx, chartArea, scales } = chart;
            ctx.save();
            current.stages.forEach(s => {
                const x0 = scales.x.getPixelForValue(s.start_s / 60);
                const x1 = scales.x.getPixelForValue((s.start_s + s.duration_s) / 60);
                ctx.fillStyle = 'rgba(124,77,255,0.16)';
                ctx.fillRect(x0, chartArea.top, Math.max(x1 - x0, 1), chartArea.bottom - chartArea.top);
                ctx.fillStyle = '#9aa6c7'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
                ctx.fillText('S' + s.stage_no, (x0 + x1) / 2, chartArea.top + 11);
            });
            ctx.restore();
        },
    };

    function drawTrace() {
        const log = current.log;
        draw('cTrace', {
            type: 'line',
            plugins: [stageBands],
            data: { datasets: [
                { label: 'Total power (W)', data: pairs(log.t_s, log.total_power_w, 1 / 60), borderColor: COLOUR.mlp, backgroundColor: COLOUR.mlp, borderWidth: 1.6, pointRadius: 0, yAxisID: 'y' },
                { label: 'Rotor power (W)', data: pairs(log.t_s, log.rotor_power_w, 1 / 60), borderColor: COLOUR.material, backgroundColor: COLOUR.material, borderWidth: 1, pointRadius: 0, yAxisID: 'y', hidden: true },
                { label: 'Pan power (W)', data: pairs(log.t_s, log.pan_power_w, 1 / 60), borderColor: COLOUR.slp, backgroundColor: COLOUR.slp, borderWidth: 1, pointRadius: 0, yAxisID: 'y', hidden: true },
                { label: 'Energy so far (kJ)', data: pairs(log.t_s, log.cumulative_energy_j, 1 / 60, 1 / 1000), borderColor: COLOUR.coincell, backgroundColor: COLOUR.coincell, borderWidth: 1.4, borderDash: [5, 4], pointRadius: 0, yAxisID: 'y2' },
            ] },
            options: {
                responsive: true, maintainAspectRatio: false, parsing: false, animation: false,
                interaction: { mode: 'nearest', axis: 'x', intersect: false },
                scales: {
                    x: axis('Time (min)', { type: 'linear' }),
                    y: axis('Power (W)', { beginAtZero: true }),
                    y2: axis('Energy (kJ)', { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false } }),
                },
                plugins: { legend, tooltip: { callbacks: { title: items => 'At ' + num(items[0].parsed.x, 1) + ' min' } } },
            },
        });
    }

    function drawStages() {
        const s = current.stages;
        draw('cStages', {
            data: {
                labels: s.map(r => 'Stage ' + r.stage_no),
                datasets: [
                    { type: 'bar', label: 'Mean power (W)', data: s.map(r => r.mean_power_w),
                      backgroundColor: s.map(r => r.rotor_rpm >= HIGH_RPM ? COLOUR.mlp : COLOUR.material),
                      borderRadius: 6, order: 2 },
                    { type: 'line', label: 'Peak power (W)', data: s.map(r => r.peak_power_w),
                      borderColor: COLOUR.coincell, backgroundColor: COLOUR.coincell, pointRadius: 4, borderWidth: 1.5, order: 1 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { x: axis(), y: axis('Power (W)', { beginAtZero: true }) },
                plugins: { legend, tooltip: { callbacks: { afterBody: items => {
                    const r = s[items[0].dataIndex];
                    return [`${num(r.rotor_rpm, 0)} rpm rotor · ${num(r.pan_rpm, 0)} rpm pan`,
                            `${num(r.duration_s, 0)} s running · ${num(r.pause_before_s, 0)} s pause before`,
                            `${num(r.energy_kj, 1)} kJ`];
                } } } },
            },
        });
    }

    function drawLineage() {
        const run = current.run;
        const nodes = [], edges = [];
        const node = (id, group, label, level, size) => nodes.push({
            id, label, level, shape: 'dot', size: size || 14, borderWidth: 2,
            color: { background: COLOUR[group], border: BORDER[group] },
            font: { color: '#e8e8f0', size: 12 },
            shadow: { enabled: true, color: COLOUR[group], size: 10, x: 0, y: 0 },
            title: id,
        });
        const edge = (from, to, label, hover) => edges.push({
            from, to, label, title: hover, arrows: 'to', width: 1.5,
            color: { color: 'rgba(120,140,200,0.45)' }, font: { color: '#9aa6c7', size: 10, strokeWidth: 0 },
            smooth: { type: 'cubicBezier', roundness: 0.4 },
        });
        node(run.mixing_id, 'mixing', run.mixing_id, 1, 22);
        current.ingredients.forEach(i => {
            node(i.material_id, 'material', i.material_id, 0);
            edge(i.material_id, run.mixing_id, i.mass_g !== null ? num(i.mass_g, 1, ' g') : '', i.role);
        });
        current.coatings.forEach(c => {
            node(c.coating_id, 'coating', c.coating_id.split('-').slice(-1)[0], 2);
            edge(run.mixing_id, c.coating_id);
        });
        current.cells.forEach(c => {
            if (!nodes.some(n => n.id === c.id)) node(c.id, c.type, c.id, 3);
            edge(c.coating_id, c.id);
        });

        const el = document.getElementById('mxNetwork');
        if (network) network.destroy();
        network = new vis.Network(el, { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) }, {
            layout: { hierarchical: { direction: 'UD', sortMethod: 'directed', levelSeparation: 130, nodeSpacing: 150 } },
            physics: false,
            interaction: { hover: true, tooltipDelay: 100 },
        });
        network.on('doubleClick', params => {
            const id = params.nodes[0];
            if (id && id !== run.mixing_id) window.location.href = '/card/' + encodeURIComponent(id);
        });
    }

    function drawModel() {
        const stats = document.getElementById('mxModelStats');
        if (!modelResult) return;
        const m = modelResult;
        const better = m.r2 > m.baseline_r2;
        stats.innerHTML =
            `<span class="mx-chip ${better ? 'good' : ''}">R² ${num(m.r2, 2)}</span>` +
            `<span class="mx-chip">Error ${num(m.mae_w, 0)} W</span>` +
            `<span class="mx-chip">Guessing the average: R² ${num(m.baseline_r2, 2)}, ${num(m.baseline_mae_w, 0)} W</span>` +
            `<span class="mx-chip">${m.runs} run${m.runs === 1 ? '' : 's'} · ${m.stages} stages</span>`;
        document.getElementById('mxModelNote').textContent = m.runs < 3
            ? `Trained on ${m.runs} run${m.runs === 1 ? '' : 's'}. With so few this shows the method, not a reliable model. Each stage is predicted by a model that never saw it.`
            : 'Each stage is predicted by a model that never saw it.';

        const id = current && m.per_run[current.run.mixing_id] ? current.run.mixing_id : Object.keys(m.per_run)[0];
        const r = m.per_run[id];
        draw('cModelTrace', {
            type: 'line',
            data: { datasets: [
                { label: 'Measured (W)', data: r.t_s.map((t, i) => ({ x: t / 60, y: r.actual[i] })), borderColor: COLOUR.mlp, backgroundColor: COLOUR.mlp, pointRadius: 1.5, showLine: false },
                { label: 'Predicted (W)', data: r.t_s.map((t, i) => ({ x: t / 60, y: r.predicted[i] })), borderColor: COLOUR.material, backgroundColor: COLOUR.material, pointRadius: 1.5, showLine: false },
            ] },
            options: { responsive: true, maintainAspectRatio: false, parsing: false, animation: false,
                scales: { x: axis('Time (min), rotor-on seconds of ' + id, { type: 'linear' }), y: axis('Power (W)') },
                plugins: { legend } },
        });
        const top = Math.ceil(Math.max(...m.scatter.actual, ...m.scatter.predicted) / 50) * 50;
        draw('cModelScatter', {
            type: 'scatter',
            data: { datasets: [
                { label: 'Seconds', data: m.scatter.actual.map((a, i) => ({ x: a, y: m.scatter.predicted[i] })), backgroundColor: 'rgba(124,77,255,0.6)', pointRadius: 2 },
                { label: 'Perfect', type: 'line', data: [{ x: 0, y: 0 }, { x: top, y: top }], borderColor: '#e8e8f0', borderDash: [4, 4], pointRadius: 0, borderWidth: 1 },
            ] },
            options: { responsive: true, maintainAspectRatio: false, parsing: false, animation: false,
                scales: { x: axis('Measured (W)', { type: 'linear', min: 0, max: top }), y: axis('Predicted (W)', { min: 0, max: top }) },
                plugins: { legend: { display: false } } },
        });
        draw('cModelImportance', {
            type: 'bar',
            data: { labels: m.importance.map(i => i.feature), datasets: [{ label: 'Drop in R² when shuffled', data: m.importance.map(i => i.value), backgroundColor: COLOUR.coating, borderRadius: 4 }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
                scales: { x: axis('What the model relies on'), y: axis() }, plugins: { legend: { display: false } } },
        });
    }

    async function trainModel() {
        const stats = document.getElementById('mxModelStats');
        stats.innerHTML = '<span class="mx-chip">Training…</span>';
        try {
            const reply = await fetch('/api/mixing/model');
            const data = await reply.json();
            if (!reply.ok) { stats.innerHTML = `<span class="mx-chip">${esc(data.error || 'Could not train.')}</span>`; return; }
            modelResult = data;
            drawModel();
        } catch (e) {
            stats.innerHTML = '<span class="mx-chip">Could not reach the server.</span>';
        }
    }

    // ---- summary panel ----------------------------------------------------------

    function renderPanel() {
        const { run, ingredients, coatings, cells, stages } = current;
        const row = (label, value) => `<div class="row"><span class="label">${esc(label)}</span><span class="value">${value}</span></div>`;
        const ing = ingredients.length
            ? ingredients.map(i => `<div><span><a href="/card/${encodeURIComponent(i.material_id)}">${esc(i.material_id)}</a>${i.role ? ' · ' + esc(i.role) : ''}</span><span>${i.mass_g !== null ? num(i.mass_g, 1, ' g') : '—'}</span></div>`).join('')
            : '<div><span class="muted">None recorded</span></div>';
        const links = (items, path) => items.length
            ? items.map(i => `<div><a href="${path}${encodeURIComponent(i)}">${esc(i)}</a></div>`).join('')
            : '<div><span class="muted">None linked yet</span></div>';
        const panel = document.getElementById('mxPanel');
        panel.innerHTML =
            `<div class="node-panel-head"><div><h3>${esc(run.mixing_id)}</h3>` +
            `<span class="type-pill"><span class="dot" style="background: var(--hz-mixing)"></span>Mixing run</span></div></div>` +
            row('Project', esc(run.project || '—')) +
            row('Mixer', esc(run.mixer || '—')) +
            row('Started', esc((run.started_at || '—').replace('T', ' ').slice(0, 19))) +
            row('Duration', minutes(run.duration_s)) +
            row('Made by', esc(run.made_by || '—')) +
            row('Stages', stages.length) +
            row('Total energy', num(run.total_energy_kj, 1, ' kJ')) +
            row('First addition', num(run.first_addition_energy_kj, 1, ' kJ')) +
            row('Knead energy', num(run.knead_energy_kj, 1, ' kJ')) +
            row('Peak power', num(run.peak_power_w, 0, ' W')) +
            row('Log file', esc(run.source_filename || '—')) +
            `<h4>INGREDIENTS</h4><div class="mx-list">${ing}</div>` +
            `<h4>COATINGS MADE FROM THIS SLURRY</h4><div class="mx-list">${links(coatings.map(c => c.coating_id), '/card/')}</div>` +
            `<h4>CELLS</h4><div class="mx-list">${links([...new Set(cells.map(c => c.id))], '/card/')}</div>` +
            (run.notes ? `<h4>NOTES</h4><div class="mx-list"><div>${esc(run.notes)}</div></div>` : '');
        panel.hidden = false;
    }

    // ---- wiring -----------------------------------------------------------------

    function show(name) {
        view = name;
        document.querySelectorAll('.mx-tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
        document.querySelectorAll('.mx-view').forEach(v => { v.hidden = v.id !== 'view-' + name; });
        const empty = document.getElementById('mxEmpty');
        const needsRun = name !== 'model';
        empty.hidden = !(needsRun && !current);
        document.getElementById('mxCaption').textContent = '';
        if (!current && needsRun) return;
        if (name === 'trace') {
            drawTrace();
            document.getElementById('mxCaption').textContent = 'Purple bands are rotor-on stages. Click a name in the legend to show or hide a line.';
        }
        if (name === 'stages') {
            drawStages();
            document.getElementById('mxCaption').textContent = 'Amber bars: rotor at 3000 rpm or more. Cyan: slower. Power at a fixed speed rises with slurry viscosity.';
        }
        if (name === 'lineage') {
            drawLineage();
            document.getElementById('mxCaption').textContent = 'Materials in, slurry, coatings and cells out. Double-click a node to open its card.';
        }
        if (name === 'model' && modelResult) drawModel();
    }

    async function loadRun(id) {
        const reply = await fetch('/api/mixing/' + encodeURIComponent(id));
        if (!reply.ok) { current = null; document.getElementById('mxPanel').hidden = true; show(view); return; }
        current = await reply.json();
        document.querySelectorAll('.mx-run').forEach(a => a.classList.toggle('active', a.dataset.id === id));
        history.replaceState(null, '', '/mixing?run=' + encodeURIComponent(id));
        renderPanel();
        show(view);
    }

    document.querySelectorAll('.mx-tab').forEach(t => t.addEventListener('click', () => show(t.dataset.view)));
    document.querySelectorAll('.mx-run').forEach(a => a.addEventListener('click', e => {
        e.preventDefault();
        loadRun(a.dataset.id);
    }));
    document.getElementById('mxTrain').addEventListener('click', trainModel);

    // "+ Add ingredient" copies the first ingredient block, empty
    document.getElementById('mxAddIngredient').addEventListener('click', () => {
        const holder = document.getElementById('mxIngredients');
        const copy = holder.firstElementChild.cloneNode(true);
        copy.querySelectorAll('select').forEach(s => { s.selectedIndex = 0; });
        copy.querySelectorAll('input').forEach(i => { i.value = ''; });
        holder.appendChild(copy);
    });

    const wanted = app.dataset.selected || (document.querySelector('.mx-run') || {}).dataset?.id;
    if (wanted) loadRun(wanted); else show('trace');
})();
