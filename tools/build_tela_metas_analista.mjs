import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const sourceDir = path.join(root, "relatorios", "projecao_positivacao");
const fontDir = path.join(root, "data", "input", "metas_bugbee_20260528");
const outputDir = path.join(root, "outputs", "tela_metas_analista");
const htmlPath = path.join(outputDir, "metas_crm_analista_bugbee.html");

const months = ["Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  for (let i = 0; i < clean.length; i += 1) {
    const ch = clean[i];
    const next = clean[i + 1];
    if (ch === '"') {
      if (inQuotes && next === '"') {
        cell += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && next === "\n") i += 1;
      row.push(cell);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    if (row.some((value) => value !== "")) rows.push(row);
  }
  return rows;
}

async function readCsv(name) {
  const text = await fs.readFile(path.join(sourceDir, name), "utf8");
  const rows = parseCsv(text);
  const headers = rows[0];
  return rows.slice(1).map((values) => Object.fromEntries(headers.map((h, i) => [h, values[i] ?? ""])));
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatInt(value) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(number(value));
}

function monthClass(index) {
  if (index <= 1) return "near";
  if (index <= 3) return "mid";
  return "late";
}

async function copyFont(file) {
  const source = path.join(fontDir, file);
  const target = path.join(outputDir, "fonts", file);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.copyFile(source, target);
}

async function main() {
  const metas = await readCsv("metas_positivacao_futuras.csv");
  const clientes = await readCsv("clientes_priorizados_positivacao.csv");
  const metodologia = JSON.parse(await fs.readFile(path.join(sourceDir, "metodologia_projecao.json"), "utf8"));

  await fs.mkdir(outputDir, { recursive: true });
  await copyFont("Rubrik.otf");
  await copyFont("Rubrik SemiBold.otf");
  await copyFont("Rubrik Bold.otf");

  const totalMeta = metas.reduce((sum, row) => sum + number(row.meta_positivacao_clientes), 0);
  const totalPriorizados = metas.reduce((sum, row) => sum + number(row.clientes_priorizados), 0);
  const taxaMedia = Math.round(metas.reduce((sum, row) => sum + number(row.taxa_recompra_proj_pct), 0) / metas.length);
  const clientesPorMes = new Map();
  for (const cliente of clientes) {
    clientesPorMes.set(cliente.mes_recomendado, (clientesPorMes.get(cliente.mes_recomendado) || 0) + 1);
  }

  const rowsHtml = metas
    .map((row, index) => {
      const meta = number(row.meta_positivacao_clientes);
      const priorizados = number(row.clientes_priorizados);
      const fill = meta ? Math.min(100, Math.round((priorizados / meta) * 100)) : 0;
      return `
        <article class="month-card ${monthClass(index)}">
          <div class="month-top">
            <span>${row.mes}</span>
            <strong>${row.taxa_recompra_proj_pct}%</strong>
          </div>
          <div class="goal-number">${formatInt(meta)}</div>
          <div class="goal-label">clientes para positivar</div>
          <div class="support-row">
            <span>Base priorizada</span>
            <b>${formatInt(priorizados)}</b>
          </div>
          <div class="support-row muted">
            <span>Compradores projetados</span>
            <b>${formatInt(row.compradores_projetados)}</b>
          </div>
          <div class="progress" aria-label="Cobertura da base priorizada">
            <i style="width:${fill}%"></i>
          </div>
          <small>${fill}% da meta coberta pela lista atual</small>
        </article>`;
    })
    .join("");

  const focusHtml = metas
    .filter((row) => number(row.clientes_priorizados) > 0)
    .map((row) => {
      const count = clientesPorMes.get(row.ano_mes) || 0;
      return `<li><span>${row.mes}</span><strong>${formatInt(count)} clientes únicos</strong></li>`;
    })
    .join("");

  const html = `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Bugbee | Metas CRM</title>
  <style>
    @font-face {
      font-family: "Rubrik";
      src: url("./fonts/Rubrik.otf") format("opentype");
      font-weight: 400;
    }
    @font-face {
      font-family: "Rubrik";
      src: url("./fonts/Rubrik SemiBold.otf") format("opentype");
      font-weight: 600;
    }
    @font-face {
      font-family: "Rubrik";
      src: url("./fonts/Rubrik Bold.otf") format("opentype");
      font-weight: 700;
    }
    :root {
      --ink: #073747;
      --ink-2: #0b4555;
      --orange: #aa4a1f;
      --orange-2: #c45c27;
      --cream: #fbf7f1;
      --line: #d8d0c8;
      --green: #0a7a52;
      --red: #b42318;
      --text: #102a34;
      --muted: #60717a;
      --white: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--cream);
      color: var(--text);
      font-family: "Rubrik", Arial, sans-serif;
      letter-spacing: 0;
    }
    .screen {
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px;
    }
    header {
      background: var(--ink);
      color: var(--white);
      padding: 24px 28px;
      border-radius: 4px;
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
    }
    h1 {
      margin: 0;
      font-size: 30px;
      line-height: 1.05;
      font-weight: 700;
    }
    .subtitle {
      margin-top: 8px;
      color: #d9e8ed;
      font-size: 14px;
      max-width: 760px;
    }
    .badge {
      border: 1px solid rgba(255,255,255,.42);
      padding: 10px 14px;
      border-radius: 3px;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 600;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 14px;
      margin: 18px 0;
    }
    .kpi {
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 4px;
      overflow: hidden;
    }
    .kpi span {
      display: block;
      background: var(--orange);
      color: var(--white);
      padding: 8px 12px;
      text-align: center;
      font-size: 13px;
      font-weight: 700;
    }
    .kpi strong {
      display: block;
      padding: 18px 12px;
      text-align: center;
      font-size: 30px;
      color: var(--ink);
      line-height: 1;
    }
    .kpi:nth-child(2) span { background: var(--green); }
    .kpi:nth-child(3) span { background: var(--ink-2); }
    .months {
      display: grid;
      grid-template-columns: repeat(7, minmax(132px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .month-card {
      background: var(--white);
      border: 1px solid var(--line);
      border-top: 7px solid var(--ink);
      border-radius: 4px;
      min-height: 230px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 9px;
    }
    .month-card.mid { border-top-color: var(--orange); }
    .month-card.late { border-top-color: var(--green); }
    .month-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      color: var(--ink);
      font-weight: 700;
      font-size: 15px;
    }
    .month-top strong {
      background: var(--cream);
      color: var(--orange);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 13px;
      white-space: nowrap;
    }
    .goal-number {
      color: var(--ink);
      font-size: 42px;
      line-height: .95;
      font-weight: 700;
      margin-top: 8px;
    }
    .goal-label {
      color: var(--muted);
      font-size: 13px;
      min-height: 30px;
    }
    .support-row {
      border-top: 1px solid var(--line);
      padding-top: 8px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
    }
    .support-row b { color: var(--ink); }
    .muted { color: var(--muted); }
    .progress {
      height: 9px;
      background: #eadfd6;
      border-radius: 999px;
      overflow: hidden;
      margin-top: auto;
    }
    .progress i {
      display: block;
      height: 100%;
      background: var(--green);
      border-radius: inherit;
    }
    small {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
    }
    .bottom {
      display: grid;
      grid-template-columns: 1fr 1.3fr;
      gap: 16px;
      margin-top: 18px;
    }
    .panel {
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 12px;
      color: var(--ink);
      font-size: 18px;
    }
    .panel ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }
    .panel li {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
      font-size: 14px;
    }
    .panel p {
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
    }
    @media (max-width: 1040px) {
      .months { grid-template-columns: repeat(2, 1fr); }
      .kpis, .bottom { grid-template-columns: 1fr; }
      header { display: block; }
      .badge { display: inline-block; margin-top: 16px; }
    }
    @media print {
      body { background: white; }
      .screen { padding: 14px; max-width: none; }
      .months { grid-template-columns: repeat(4, 1fr); }
    }
  </style>
</head>
<body>
  <main class="screen">
    <header>
      <div>
        <h1>Metas de Positivação CRM</h1>
        <div class="subtitle">Visão simplificada para execução mensal. Positivação = cliente único que recompra dentro da janela de 180 dias.</div>
      </div>
      <div class="badge">Junho a Dezembro de 2026</div>
    </header>

    <section class="kpis">
      <div class="kpi"><span>Meta total de clientes</span><strong>${formatInt(totalMeta)}</strong></div>
      <div class="kpi"><span>Clientes já priorizados</span><strong>${formatInt(totalPriorizados)}</strong></div>
      <div class="kpi"><span>Taxa média projetada</span><strong>${taxaMedia}%</strong></div>
    </section>

    <section class="months" aria-label="Metas mensais">
      ${rowsHtml}
    </section>

    <section class="bottom">
      <div class="panel">
        <h2>Base de trabalho</h2>
        <ul>${focusHtml}</ul>
      </div>
      <div class="panel">
        <h2>Critério usado</h2>
        <p>O RFM usa ${metodologia.periodo_rfm_dias} dias de histórico, refletindo a frequência média de 2 a 3 compras por ano. A janela de positivação é de ${metodologia.janela_positivacao_dias} dias; o mesmo cliente não é repetido entre os meses da lista priorizada.</p>
      </div>
    </section>
  </main>
</body>
</html>`;

  await fs.writeFile(htmlPath, html, "utf8");
  console.log(htmlPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
