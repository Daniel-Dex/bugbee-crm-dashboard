import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const relatoriosDir = path.join(root, "relatorios");
const outputDir = path.join(root, "outputs", "recompra_crm");
const outputPath = path.join(outputDir, "relatorio_recompra_crm_formatado.xlsx");
const previewDir = path.join(outputDir, "previews");

const theme = {
  navy: "#0B1F33",
  teal: "#006B5B",
  mint: "#E6F4F1",
  blue: "#1D4ED8",
  amber: "#B45309",
  red: "#B91C1C",
  green: "#047857",
  surface: "#F3F6F8",
  border: "#B8C4D0",
  text: "#111827",
  muted: "#334155",
  white: "#FFFFFF",
};

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
  const text = await fs.readFile(path.join(relatoriosDir, name), "utf8");
  const rows = parseCsv(text);
  const headers = rows[0];
  return rows.slice(1).map((values) => {
    const obj = {};
    headers.forEach((header, idx) => {
      obj[header] = values[idx] ?? "";
    });
    return obj;
  });
}

function n(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(",", "."));
  return Number.isFinite(parsed) ? parsed : value;
}

function excelCol(index) {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function matrix(rows, columns, numericColumns = new Set(), headers = columns) {
  return [
    headers,
    ...rows.map((row) =>
      columns.map((column) => (numericColumns.has(column) ? n(row[column]) : row[column])),
    ),
  ];
}

function setWidths(sheet, widths) {
  widths.forEach((width, idx) => {
    sheet.getRange(`${excelCol(idx)}:${excelCol(idx)}`).format.columnWidthPx = width;
  });
}

function styleTitle(sheet, rangeAddress, title) {
  const range = sheet.getRange(rangeAddress);
  range.merge();
  range.values = [[title]];
  range.format = {
    fill: theme.navy,
    font: { bold: true, color: theme.white, size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  range.format.rowHeightPx = 34;
}

function styleSubtitle(sheet, rangeAddress, text) {
  const range = sheet.getRange(rangeAddress);
  range.merge();
  range.values = [[text]];
  range.format = {
    fill: theme.surface,
    font: { color: theme.muted, size: 10 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
    wrapText: true,
  };
  range.format.rowHeightPx = 34;
}

function addTableSheet(
  workbook,
  sheetName,
  rows,
  columns,
  numericColumns,
  tableName,
  numberFormats = {},
  displayHeaders = columns,
) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  styleTitle(sheet, `A1:${excelCol(columns.length - 1)}1`, sheetName);
  styleSubtitle(sheet, `A2:${excelCol(columns.length - 1)}2`, "Fonte: API Magazord. Dados tratados e classificados pelo pipeline de recompradores.");
  const data = matrix(rows, columns, numericColumns, displayHeaders);
  const endCol = excelCol(columns.length - 1);
  const endRow = data.length + 3;
  sheet.getRange(`A4:${endCol}${endRow}`).values = data;
  sheet.tables.add(`A4:${endCol}${endRow}`, true, tableName).style = "TableStyleMedium2";
  sheet.freezePanes.freezeRows(4);
  Object.entries(numberFormats).forEach(([column, format]) => {
    const idx = columns.indexOf(column);
    if (idx >= 0) {
      sheet.getRange(`${excelCol(idx)}5:${excelCol(idx)}${endRow}`).format.numberFormat = format;
    }
  });
  sheet.getRange(`A4:${endCol}${endRow}`).format = {
    font: { color: theme.text, size: 10 },
    verticalAlignment: "center",
  };
  const header = sheet.getRange(`A4:${endCol}4`);
  header.format = {
    fill: theme.navy,
    font: { bold: true, color: theme.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  header.format.rowHeightPx = 34;
  return sheet;
}

function addKpiCard(sheet, address, label, value, accent = theme.teal, numberFormat = null) {
  const range = sheet.getRange(address);
  range.format = {
    fill: theme.white,
    font: { color: theme.text },
    borders: { outside: { style: "continuous", color: theme.border, weight: "thin" } },
  };
  const [start, end] = address.split(":");
  const startCol = start.match(/[A-Z]+/)[0];
  const startRow = Number(start.match(/\d+/)[0]);
  const endCol = end.match(/[A-Z]+/)[0];
  sheet.getRange(`${startCol}${startRow}:${endCol}${startRow}`).merge();
  sheet.getRange(`${startCol}${startRow}:${endCol}${startRow}`).values = [[label]];
  sheet.getRange(`${startCol}${startRow}:${endCol}${startRow}`).format = {
    fill: accent,
    font: { bold: true, color: theme.white, size: 10 },
    horizontalAlignment: "center",
  };
  sheet.getRange(`${startCol}${startRow + 1}:${endCol}${startRow + 2}`).merge();
  sheet.getRange(`${startCol}${startRow + 1}:${endCol}${startRow + 2}`).values = [[value]];
  sheet.getRange(`${startCol}${startRow + 1}:${endCol}${startRow + 2}`).format = {
    fill: theme.white,
    font: { bold: true, color: theme.text, size: 18 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  if (numberFormat) {
    sheet.getRange(`${startCol}${startRow + 1}:${endCol}${startRow + 2}`).format.numberFormat = numberFormat;
  }
}

function monthLabel(anoMes) {
  return String(anoMes);
}

function parsePercentInteger(value) {
  const parsed = n(value);
  return typeof parsed === "number" ? parsed / 100 : parsed;
}

async function main() {
  const recompradores = await readCsv("recompradores_mensal.csv");
  const metas = await readCsv("metas_mensais.csv");
  const inativos = await readCsv("inativos_recuperaveis.csv");
  const resumo = JSON.parse(await fs.readFile(path.join(relatoriosDir, "resumo_dashboard.json"), "utf8"));
  const metodologia = await fs.readFile(path.join(relatoriosDir, "metodologia_meta.md"), "utf8");

  const workbook = Workbook.create();

  const dashboard = workbook.worksheets.add("Dashboard");
  dashboard.showGridLines = false;
  styleTitle(dashboard, "A1:L1", "Relatorio CRM - Recompradores e Inativos");
  styleSubtitle(
    dashboard,
    "A2:L2",
    "Resumo executivo do mes mais recente, metas automaticas sazonais e base de inativos recuperaveis para acao de CRM.",
  );
  setWidths(dashboard, [120, 150, 140, 135, 130, 130, 24, 110, 110, 110, 110, 110]);

  addKpiCard(dashboard, "A4:C6", "Mes mais recente", resumo.ano_mes, theme.navy);
  addKpiCard(dashboard, "D4:F6", "Recompradores 180d", resumo.recompradores, theme.teal, "0");
  addKpiCard(dashboard, "H4:J6", "Meta base", resumo.meta_base, theme.blue, "0");
  addKpiCard(dashboard, "K4:L6", "Atingimento", resumo.percentual_atingimento / 100, resumo.status === "abaixo" ? theme.red : theme.green, "0%");
  addKpiCard(dashboard, "A8:C10", "Status", resumo.status, resumo.status === "abaixo" ? theme.red : theme.green);
  addKpiCard(dashboard, "D8:F10", "Nao positivados", resumo.novos_clientes, theme.amber, "0");
  addKpiCard(dashboard, "H8:J10", "Taxa recompra", resumo.taxa_recompra / 100, theme.teal, "0%");
  addKpiCard(dashboard, "K8:L10", "Crescimento alvo", resumo.crescimento_alvo_pct / 100, theme.blue, "0%");
  addKpiCard(dashboard, "A12:C14", "Inativos 90d", resumo.total_inativos_90d, theme.amber, "0");
  addKpiCard(dashboard, "D12:F14", "Inativos 180d", resumo.total_inativos_180d, theme.red, "0");

  dashboard.getRange("A16:L16").merge();
  dashboard.getRange("A16:L16").values = [["Tendencia mensal"]];
  dashboard.getRange("A16:L16").format = {
    fill: theme.navy,
    font: { bold: true, color: theme.white },
    horizontalAlignment: "center",
  };

  const chartRows = recompradores.slice(-18).map((row) => [
    monthLabel(row.ano_mes),
    n(row.recompradores),
    n(row.novos_clientes),
    parsePercentInteger(row.taxa_recompra),
  ]);
  dashboard.getRange(`A18:D${18 + chartRows.length}`).values = [
    ["Mes", "Recompradores 180d", "Nao positivados", "Taxa recompra"],
    ...chartRows,
  ];
  dashboard.getRange(`A18:D18`).format = {
    fill: theme.teal,
    font: { bold: true, color: theme.white },
    horizontalAlignment: "center",
  };
  dashboard.getRange(`B19:C${18 + chartRows.length}`).format.numberFormat = "0";
  dashboard.getRange(`D19:D${18 + chartRows.length}`).format.numberFormat = "0%";
  dashboard.tables.add(`A18:D${18 + chartRows.length}`, true, "DashboardTrendTable").style = "TableStyleMedium4";

  const chart = dashboard.charts.add("line", dashboard.getRange(`A18:C${18 + chartRows.length}`));
  chart.title = "Recompradores 180d vs nao positivados";
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis", tickLabelInterval: 2 };
  chart.yAxis = { numberFormatCode: "#,##0" };
  chart.setPosition("F18", "L34");

  const metaRows = metas.slice(-12).map((row) => [
    row.ano_mes,
    n(row.recompradores_realizados),
    n(row.meta_base),
    parsePercentInteger(row.percentual_atingimento),
    row.status,
  ]);
  dashboard.getRange(`A37:E${37 + metaRows.length}`).values = [
    ["Mes", "Realizado", "Meta base", "Atingimento", "Status"],
    ...metaRows,
  ];
  dashboard.getRange("A37:E37").format = {
    fill: theme.navy,
    font: { bold: true, color: theme.white },
    horizontalAlignment: "center",
  };
  dashboard.getRange(`B38:C${37 + metaRows.length}`).format.numberFormat = "0";
  dashboard.getRange(`D38:D${37 + metaRows.length}`).format.numberFormat = "0%";
  dashboard.tables.add(`A37:E${37 + metaRows.length}`, true, "DashboardGoalTable").style = "TableStyleMedium9";
  dashboard.freezePanes.freezeRows(2);

  const recompradoresColumns = [
    "ano_mes",
    "total_pedidos",
    "compradores_unicos",
    "recompradores",
    "novos_clientes",
    "taxa_recompra",
    "receita_total",
    "receita_recompradores",
    "ticket_medio_recompradores",
    "ticket_medio_novos",
  ];
  const recompradoresSheet = addTableSheet(
    workbook,
    "Recompradores Mensal",
    recompradores,
    recompradoresColumns,
    new Set(recompradoresColumns.filter((c) => c !== "ano_mes")),
    "RecompradoresMensal",
    {
      total_pedidos: "#,##0",
      compradores_unicos: "#,##0",
      recompradores: "#,##0",
      novos_clientes: "#,##0",
      taxa_recompra: '0"%"',
      receita_total: '"R$" 0',
      receita_recompradores: '"R$" 0',
      ticket_medio_recompradores: '"R$" 0',
      ticket_medio_novos: '"R$" 0',
    },
    [
      "Ano mes",
      "Total pedidos",
      "Compradores unicos",
      "Recompradores 180d",
      "Nao positivados",
      "Taxa recompra",
      "Receita total",
      "Receita recompradores",
      "Ticket recompradores",
      "Ticket novos",
    ],
  );
  setWidths(recompradoresSheet, [90, 95, 120, 110, 105, 105, 120, 145, 170, 140]);

  const metasColumns = [
    "ano_mes",
    "baseline_yoy",
    "crescimento_alvo_pct",
    "meta_base",
    "faixa_minima",
    "meta_stretch",
    "recompradores_realizados",
    "percentual_atingimento",
    "status",
    "justificativa",
  ];
  const metasSheet = addTableSheet(
    workbook,
    "Metas Mensais",
    metas,
    metasColumns,
    new Set(metasColumns.filter((c) => !["ano_mes", "status", "justificativa"].includes(c))),
    "MetasMensais",
    {
      baseline_yoy: "0",
      crescimento_alvo_pct: '0"%"',
      meta_base: "0",
      faixa_minima: "0",
      meta_stretch: "0",
      recompradores_realizados: "0",
      percentual_atingimento: '0"%"',
    },
    [
      "Ano mes",
      "Baseline YoY",
      "Cresc. alvo",
      "Meta base",
      "Faixa minima",
      "Meta stretch",
      "Realizado",
      "Atingimento",
      "Status",
      "Justificativa",
    ],
  );
  setWidths(metasSheet, [90, 105, 95, 100, 105, 105, 90, 95, 90, 470]);
  metasSheet.getRange(`J5:J${metas.length + 4}`).format.wrapText = true;
  metasSheet.getRange(`J5:J${metas.length + 4}`).format = {
    font: { color: theme.text, size: 9 },
    wrapText: true,
    verticalAlignment: "top",
  };
  metasSheet.getRange(`A5:J${metas.length + 4}`).format.rowHeightPx = 86;

  const inativosColumns = ["cliente_id", "data_ultima_compra", "dias_inativo", "faixa_inatividade"];
  const inativosSheet = addTableSheet(
    workbook,
    "Inativos Recuperaveis",
    inativos,
    inativosColumns,
    new Set(["dias_inativo"]),
    "InativosRecuperaveis",
    { dias_inativo: "#,##0" },
    ["Cliente ID", "Data ultima compra", "Dias inativo", "Faixa inatividade"],
  );
  setWidths(inativosSheet, [130, 145, 120, 140]);

  const metodologiaSheet = workbook.worksheets.add("Metodologia");
  metodologiaSheet.showGridLines = false;
  styleTitle(metodologiaSheet, "A1:H1", "Metodologia da meta");
  const paragraphs = metodologia
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => [line.replace(/^#+\s*/, "").replace(/^\-\s*/, "• ")]);
  metodologiaSheet.getRange(`A3:A${paragraphs.length + 2}`).values = paragraphs;
  metodologiaSheet.getRange(`A3:A${paragraphs.length + 2}`).format = {
    font: { color: theme.text, size: 10 },
    wrapText: true,
    verticalAlignment: "top",
  };
  metodologiaSheet.getRange("A:A").format.columnWidthPx = 920;
  metodologiaSheet.getRange(`A3:A${paragraphs.length + 2}`).format.rowHeightPx = 42;

  await fs.mkdir(outputDir, { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });

  const sheetsToRender = [
    ["Dashboard", "dashboard.png", "A1:L48"],
    ["Recompradores Mensal", "recompradores_mensal.png", "A1:J24"],
    ["Metas Mensais", "metas_mensais.png", "A1:J20"],
    ["Inativos Recuperaveis", "inativos_recuperaveis.png", "A1:D30"],
    ["Metodologia", "metodologia.png", "A1:A24"],
  ];
  for (const [sheetName, fileName, range] of sheetsToRender) {
    const preview = await workbook.render({ sheetName, range, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
  }

  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 },
    summary: "final formula error scan",
  });
  console.log(errors.ndjson);

  const dashInspect = await workbook.inspect({
    kind: "table",
    range: "Dashboard!A1:L14",
    include: "values,formulas",
    tableMaxRows: 14,
    tableMaxCols: 12,
    maxChars: 4000,
  });
  console.log(dashInspect.ndjson);

  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  console.log(outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
