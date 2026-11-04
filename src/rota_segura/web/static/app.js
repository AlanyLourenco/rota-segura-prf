// Interface local do Rota Segura: formulário, agente ao vivo (SSE da trilha de auditoria) e relatório.
// Textos vindos da auditoria entram sempre via textContent; o HTML do relatório já vem saneado do servidor.
"use strict";

const $ = (id) => document.getElementById(id);

const NODE_LABELS = {
  input_guard: "Guardrail de entrada",
  route: "Rota (OpenStreetMap)",
  orchestrator: "Orquestrador (LLM)",
  tools: "Execução de tools",
  "tool:get_road_safety_metrics": "Tool · métricas (DuckDB)",
  "tool:build_report_charts": "Tool · gráficos",
  "tool:search_road_news": "Tool · notícias",
  "tool:get_victim_profile": "Tool · perfil de vítimas (LGPD)",
  collect: "Coleta de insumos",
  writer: "Redator (LLM)",
  output_guard: "Guardrail de saída",
  sanitize: "Sanitização",
  render: "Montagem do relatório",
};
const GOOD = new Set(["aprovado", "coberta"]);
const BAD = new Set(["reprovado", "rejeitado", "bloqueado"]);

let source = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (child != null) node.append(child);
  }
  return node;
}

function label(node) {
  return NODE_LABELS[node] || node;
}

function stepTitle(record) {
  const extra = record.inputs && (record.inputs.attempt || record.inputs.step);
  const suffix = record.inputs && record.inputs.attempt ? ` · tentativa ${extra}` : "";
  return label(record.node) + suffix;
}

// ------------------------------------------------------------------ linha do tempo

function resetTimeline() {
  $("timeline").replaceChildren();
  $("timeline-empty").hidden = false;
}

function lastOpenStep(node) {
  const steps = [...$("timeline").querySelectorAll(`.step[data-node="${CSS.escape(node)}"]`)];
  return steps.reverse().find((s) => s.classList.contains("running")) || steps.at(-1);
}

function addStep(record, state) {
  const title = el("div", { class: "step-title" }, el("span", {}, stepTitle(record)), el("span", { class: "step-time" }));
  const item = el("li", { class: `step ${state}`, "data-node": record.node }, title);
  const list = $("timeline");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  list.append(item);
  $("timeline-empty").hidden = true;
  if (atBottom) list.scrollTop = list.scrollHeight; // segue o agente, a menos que você tenha rolado para cima
  return item;
}

function addDecision(record) {
  const kind = GOOD.has(record.decision) ? "good" : BAD.has(record.decision) ? "bad" : "warn";
  const box = el("div", { class: `decision ${kind}` }, el("b", {}, record.decision), ` · ${record.reason || ""}`);
  if (Array.isArray(record.issues) && record.issues.length) {
    const list = el("ul");
    for (const issue of record.issues) list.append(el("li", {}, `${issue.rule}: ${issue.detail}`));
    box.append(list);
  }
  const host = lastOpenStep(record.node) || addStep(record, "done");
  host.append(box);
}

function applyEvent(record) {
  switch (record.event) {
    case "start":
      addStep(record, "running");
      break;
    case "end": {
      const step = lastOpenStep(record.node) || addStep(record, "done");
      step.classList.replace("running", "done");
      step.querySelector(".step-time").textContent = formatMs(record.duration_ms);
      break;
    }
    case "error": {
      const step = lastOpenStep(record.node) || addStep(record, "failed");
      step.classList.remove("running", "done");
      step.classList.add("failed");
      step.append(el("div", { class: "step-error" }, record.error || "erro"));
      break;
    }
    case "decision":
      addDecision(record);
      break;
    default:
      break; // tool_result, llm, artifact: ficam na trilha completa (manifesto/JSONL)
  }
}

function formatMs(ms) {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function setStatus(text, kind) {
  const badge = $("run-status");
  badge.hidden = !text;
  badge.textContent = text || "";
  badge.className = `status ${kind || ""}`;
}

// ------------------------------------------------------------------ relatório

function clearReport() {
  $("report-meta").replaceChildren();
  $("report").replaceChildren();
  $("report-frame").removeAttribute("src");
  $("manifest-json").textContent = "";
  $("report-empty").hidden = false;
  $("report-error").hidden = true;
  $("report-bar").hidden = true;
  $("report-frame").hidden = true;
  $("report").hidden = true;
  $("manifest").hidden = true;
}

function showError(title, reason, kind = "") {
  $("report-empty").hidden = true;
  const box = $("report-error");
  box.className = `error ${kind}`;
  box.replaceChildren(el("strong", {}, title), reason || "");
  box.hidden = false;
}

async function openRun(key, { replayTimeline }) {
  const resp = await fetch(`/api/runs/${key.split("/").map(encodeURIComponent).join("/")}`);
  if (!resp.ok) {
    showError("Não foi possível abrir o relatório.", `HTTP ${resp.status}`);
    return;
  }
  const run = await resp.json();
  $("report-empty").hidden = true;
  $("report-error").hidden = true;

  const meta = $("report-meta");
  const model = (run.model || "modelo n/d").split(",")[0].split(":").at(-1);
  meta.replaceChildren(
    el("span", { class: "tag" }, run.scope),
    el("span", { class: "tag" }, model),
    el("span", { class: "tag" }, `execução ${run.run_id || "n/d"}`),
  );
  $("report-bar").hidden = false;

  const frame = $("report-frame");
  const article = $("report");
  const fileUrl = run.report_url || `/files/${run.key}/relatorio.md`;
  $("report-download").href = fileUrl;
  $("report-download").setAttribute("download", run.report_url ? "relatorio.html" : "relatorio.md");
  $("report-open").href = fileUrl;
  $("report-open").hidden = !run.report_url;
  if (run.report_url) {
    // Relatório didático: o mesmo arquivo que é baixado, isolado num iframe sem permissão de script.
    article.hidden = true;
    frame.hidden = false;
    frame.onload = () => fitFrame(frame);
    frame.src = run.report_url;
  } else {
    frame.hidden = true;
    article.innerHTML = run.html; // exemplos antigos: Markdown saneado no servidor
    article.hidden = false;
  }

  $("manifest-json").textContent = run.manifest ? JSON.stringify(run.manifest, null, 2) : "Manifesto não encontrado.";
  $("manifest").hidden = false;

  if (replayTimeline) {
    resetTimeline();
    run.events.forEach(applyEvent);
    setStatus(run.events.length ? "trilha gravada" : "", "ok");
  }
  markCurrent(key);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fitFrame(frame) {
  try {
    const doc = frame.contentDocument;
    frame.style.height = `${doc.documentElement.scrollHeight + 8}px`;
    // <details> muda a altura ao abrir/fechar
    doc.querySelectorAll("details").forEach((d) => d.addEventListener("toggle", () => fitFrame(frame)));
  } catch {
    frame.style.height = "80vh";
  }
}

// ------------------------------------------------------------------ relatórios anteriores

function markCurrent(key) {
  for (const btn of $("runs").querySelectorAll("button")) {
    btn.setAttribute("aria-current", String(btn.dataset.key === key));
  }
}

async function loadRuns() {
  const runs = await (await fetch("/api/runs")).json();
  const list = $("runs");
  list.replaceChildren();
  if (!runs.length) {
    list.append(el("li", { class: "muted small" }, "Nenhum relatório ainda."));
    return;
  }
  for (const run of runs.slice(0, 15)) {
    const when = run.finished_at ? new Date(run.finished_at).toLocaleString("pt-BR") : "";
    const btn = el(
      "button",
      { type: "button", "data-key": run.key },
      el("span", {}, run.scope, el("br"), el("small", {}, when || run.key)),
      el("span", { class: "tag" }, run.example ? "exemplo" : run.model === "offline" ? "offline" : "LLM"),
    );
    btn.addEventListener("click", () => openRun(run.key, { replayTimeline: true }));
    list.append(el("li", {}, btn));
  }
}

// ------------------------------------------------------------------ geração ao vivo

function startRun(event) {
  event.preventDefault();
  if (source) source.close();
  const params = new URLSearchParams({ focus: $("focus").value.trim() });
  if (routeMode()) {
    params.set("origin", $("origin").value.trim());
    params.set("destination", $("destination").value.trim());
  } else {
    params.set("uf", $("uf").value);
  }
  if ($("offline").checked) params.set("offline", "1");
  if ($("no_news").checked) params.set("no_news", "1");

  resetTimeline();
  clearReport();
  setStatus("gerando…", "running");
  $("submit").disabled = true;

  source = new EventSource(`/api/stream?${params}`);
  source.addEventListener("audit", (e) => applyEvent(JSON.parse(e.data)));
  source.addEventListener("done", async (e) => {
    finish();
    const { key } = JSON.parse(e.data);
    setStatus("concluído", "ok");
    await openRun(key, { replayTimeline: false });
    loadRuns();
  });
  source.addEventListener("failed", (e) => {
    finish();
    const { status, reason } = JSON.parse(e.data);
    const titles = {
      rejected: "Pesquisa recusada pelo guardrail de entrada",
      not_covered: "Essa rota não passa por rodovias federais com dados da PRF",
      busy: "Outro relatório está em geração",
      error: "Falha na geração (registrada no manifesto)",
    };
    const short = { rejected: "recusado", not_covered: "sem cobertura" };
    setStatus(short[status] || "falhou", status === "not_covered" ? "running" : "bad");
    showError(titles[status] || "Falha", reason, status === "not_covered" ? "info" : "");
    loadRuns();
  });
  source.onerror = () => {
    if (!source) return;
    finish();
    setStatus("conexão perdida", "bad");
    showError("A conexão com o servidor caiu.", "Confira o terminal onde `rota-segura web` está rodando.");
  };
}

function finish() {
  if (source) source.close();
  source = null;
  $("submit").disabled = false;
}

// ------------------------------------------------------------------ modo (Brasil/UF x rota) e ajuda

function routeMode() {
  return document.querySelector('input[name="mode"]:checked').value === "route";
}

function applyMode() {
  const route = routeMode();
  $("scope-fields").hidden = route;
  $("route-fields").hidden = !route;
  $("origin").required = route;
  $("destination").required = route;
}

function showHelp() {
  clearReport();
  markCurrent(null);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ------------------------------------------------------------------ início

async function init() {
  const meta = await (await fetch("/api/meta")).json();
  for (const uf of meta.ufs) $("uf").append(el("option", { value: uf }, uf));
  const badge = $("model-badge");
  const models = meta.llm_model.split(",").map((m) => m.trim().split(":").at(-1));
  badge.textContent = `LLM: ${models[0]}` + (models.length > 1 ? ` (+${models.length - 1} reserva)` : "");
  badge.title = `Cadeia de modelos (fallback): ${models.join(" → ")}`;
  badge.hidden = false;
  if (!meta.llm_key_configured) {
    $("offline").checked = true;
    $("key-warning").hidden = false;
  }
  $("report-form").addEventListener("submit", startRun);
  for (const radio of document.querySelectorAll('input[name="mode"]')) radio.addEventListener("change", applyMode);
  $("show-help").addEventListener("click", showHelp);
  applyMode();
  await loadRuns();
}

init();
