const SOURCE_LABELS = {
  google_scholar: "Google Scholar",
  semantic_scholar: "Semantic Scholar",
  openalex: "OpenAlex",
};

const number = value => new Intl.NumberFormat("es-ES").format(value ?? 0);
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[char]));

function metric(label, value, note) {
  return `<article class="metric"><span class="metric-label">${label}</span><strong class="metric-value">${number(value)}</strong><span class="metric-note">${note}</span></article>`;
}

function chart(snapshots, sourceName) {
  const points = snapshots.map(s => ({ date: s.date, value: s.sources[sourceName]?.metrics?.citations })).filter(p => Number.isFinite(p.value));
  if (!points.length) return `<p class="error">Todavía no hay datos históricos.</p>`;
  if (points.length === 1) return `<div class="first-snapshot"><strong>${number(points[0].value)}</strong><span>PRIMER SNAPSHOT · ${points[0].date}</span><small>La trayectoria aparecerá tras la próxima recogida.</small></div>`;
  const width = 700, height = 190, padX = 12, padY = 15;
  const max = Math.max(...points.map(p => p.value), 1);
  const coords = points.map((p, i) => ({
    ...p,
    x: padX + i * ((width - padX * 2) / Math.max(points.length - 1, 1)),
    y: height - padY - (p.value / max) * (height - padY * 2),
  }));
  const line = coords.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const area = `${line} L${coords.at(-1).x},${height - padY} L${coords[0].x},${height - padY} Z`;
  const labels = coords.filter((_, i) => i === 0 || i === coords.length - 1).map(p => `<text class="chart-label" x="${p.x}" y="${height + 8}" text-anchor="${p === coords[0] ? "start" : "end"}">${p.date}</text>`).join("");
  return `<svg viewBox="0 0 ${width} ${height + 15}" role="img" aria-label="Evolución de citas"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2ad39b" stop-opacity=".28"/><stop offset="1" stop-color="#2ad39b" stop-opacity="0"/></linearGradient></defs><path d="${area}" fill="url(#area)"/><path d="${line}" fill="none" stroke="#087d5a" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>${coords.map(p => `<circle cx="${p.x}" cy="${p.y}" r="4" fill="#f3f0e8" stroke="#087d5a" stroke-width="3"/>`).join("")}<text class="chart-label" x="${coords.at(-1).x - 4}" y="${coords.at(-1).y - 14}" text-anchor="end">${max} CITAS</text>${labels}</svg>`;
}

function render(history, config) {
  const snapshots = history.snapshots || [];
  const latest = snapshots.at(-1);
  if (!latest) throw new Error("No hay snapshots en data/history.json");
  const primaryName = config.dashboard.primary_source;
  const primary = latest.sources[primaryName] || Object.values(latest.sources)[0];
  const m = primary.metrics;
  const observed = primary.observed_at || latest.date;
  document.getElementById("today").textContent = new Date(observed + "T12:00:00").toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }).toUpperCase();
  document.getElementById("statusText").textContent = latest.warnings?.length ? "Actualizado con avisos" : "Datos sincronizados";
  document.getElementById("updated").textContent = `ÚLTIMA RECOGIDA ${latest.collected_at.slice(0, 16).replace("T", " ")} UTC`;
  document.getElementById("metrics").innerHTML = [
    metric("CITAS", m.citations, SOURCE_LABELS[primaryName]),
    metric("ÍNDICE H", m.h_index, `${m.h_index} trabajos con ≥ ${m.h_index} citas`),
    metric("PUBLICACIONES", m.papers, `${latest.papers.filter(p => p.year === new Date().getFullYear() && primaryName in p.sources).length} este año`),
    metric("ÍNDICE I10", m.i10_index, "Trabajos con ≥ 10 citas"),
  ].join("");
  document.getElementById("chart").innerHTML = chart(snapshots, primaryName);

  const papers = latest.papers.map(p => ({ ...p, citations: p.sources[primaryName] ?? Math.max(...Object.values(p.sources)) })).sort((a, b) => b.citations - a.citations).slice(0, 5);
  document.getElementById("topPapers").innerHTML = papers.map((p, i) => `<div class="paper"><span class="rank">0${i + 1}</span><div><div class="paper-title">${escapeHtml(p.title)}</div><div class="paper-year">${p.year || "—"}</div></div><div class="cite-count">${p.citations}<small>CITAS</small></div></div>`).join("");

  document.getElementById("sources").innerHTML = Object.entries(latest.sources).map(([name, source]) => `<div class="source"><div class="source-name">${SOURCE_LABELS[name] || name}</div><strong>${number(source.metrics.citations)}</strong><span>CITAS</span><dl><div><dt>Papers</dt><dd>${source.metrics.papers}</dd></div><div><dt>h-index</dt><dd>${source.metrics.h_index}</dd></div><div><dt>Observado</dt><dd>${source.observed_at || latest.date}</dd></div></dl></div>`).join("");

  const goals = [
    ["Citas totales", m.citations, config.dashboard.citation_milestone],
    ["Publicaciones", m.papers, config.dashboard.paper_milestone],
  ];
  document.getElementById("milestones").innerHTML = goals.map(([label, current, goal]) => `<div class="milestone"><div class="milestone-top"><span>${label}</span><span>${current} / ${goal}</span></div><div class="track"><div class="fill" style="width:${Math.min(100, current / goal * 100)}%"></div></div></div>`).join("");
}

Promise.all([fetch("data/history.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }), fetch("config.json").then(r => r.json())])
  .then(([history, config]) => render(history, config))
  .catch(error => { document.getElementById("metrics").innerHTML = `<p class="error">No se pudieron cargar los datos. Ejecuta <code>python collector.py</code> y abre la web mediante un servidor local. (${escapeHtml(error.message)})</p>`; });
