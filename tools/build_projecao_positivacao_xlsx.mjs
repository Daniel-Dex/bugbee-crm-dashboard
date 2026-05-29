import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const sourceDir = path.join(root, "relatorios", "projecao_positivacao");
const outputDir = path.join(root, "outputs", "projecao_positivacao");
const previewDir = path.join(outputDir, "previews");
const outputPath = path.join(outputDir, "projecao_positivacao_bugbee.xlsx");

const brand = {
  ink: "#073747",
  ink2: "#0B4555",
  orange: "#AA4A1F",
  orange2: "#C45C27",
  gray: "#737373",
  lightGray: "#F0F2F3",
  cream: "#FBF7F1",
  white: "#FFFFFF",
  line: "#B8C4C9",
  green: "#0A7A52",
  red: "#B42318",
  blue: "#185ABC",
  font: "Rubrik",
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
  const text = await fs.readFile(path.join(sourceDir, name), "utf8");
  const rows = parseCsv(text);
  const headers = rows[0];
  return rows.slice(1).map((values) => Object.fromEntries(headers.map((h, i) => [h, values[i] ?? ""])));
}

function n(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(",", "."));
  return Number.isFinite(parsed) ? parsed : value;
}

function col(index) {
  let x = index + 1;
  let out = "";
  while (x > 0) {
    const rem = (x - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    x = Math.floor((x - 1) / 26);
  }
  return out;
}

function setWidths(sheet, widths) {
  widths.forEach((width, idx) => {
    sheet.getRange(`${col(idx)}:${col(idx)}`).format.columnWidthPx = width;
  });
}

function title(sheet, address, text) {
  const r = sheet.getRange(address);
  r.merge();
  r.values = [[text]];
  r.format = {
    fill: brand.ink,
    font: { bold: true, color: brand.white, size: 18, name: brand.font },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  r.format.rowHeightPx = 40;
}

function subtitle(sheet, address, text) {
  const r = sheet.getRange(address);
  r.merge();
  r.values = [[text]];
  r.format = {
    fill: brand.cream,
    font: { color: brand.ink, size: 10, name: brand.font },
    horizontalAlignment: "left",
    verticalAlignment: "center",
    wrapText: true,
  };
  r.format.rowHeightPx = 34;
}

function card(sheet, address, label, value, fill, format = null) {
  const [start, end] = address.split(":");
  const c1 = start.match(/[A-Z]+/)[0];
  const r1 = Number(start.match(/\d+/)[0]);
  const c2 = end.match(/[A-Z]+/)[0];
  sheet.getRange(address).format = {
    fill: brand.white,
    borders: { outside: { style: "continuous", color: brand.line, weight: "thin" } },
  };
  sheet.getRange(`${c1}${r1}:${c2}${r1}`).merge();
  sheet.getRange(`${c1}${r1}:${c2}${r1}`).values = [[label]];
  sheet.getRange(`${c1}${r1}:${c2}${r1}`).format = {
    fill,
    font: { bold: true, color: brand.white, name: brand.font },
    horizontalAlignment: "center",
  };
  sheet.getRange(`${c1}${r1 + 1}:${c2}${r1 + 2}`).merge();
  sheet.getRange(`${c1}${r1 + 1}:${c2}${r1 + 2}`).values = [[value]];
  sheet.getRange(`${c1}${r1 + 1}:${c2}${r1 + 2}`).format = {
    fill: brand.white,
    font: { bold: true, color: brand.ink, size: 20, name: brand.font },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  if (format) sheet.getRange(`${c1}${r1 + 1}:${c2}${r1 + 2}`).format.numberFormat = format;
}

function addTable(workbook, sheetName, rows, columns, headers, numericColumns, formats, widths, tableName) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  title(sheet, `A1:${col(columns.length - 1)}1`, sheetName);
  subtitle(sheet, `A2:${col(columns.length - 1)}2`, "Cliente unico, positivacao em ate 180 dias e numeros inteiros para meta e bonificacao.");
  setWidths(sheet, widths);
  const matrix = [
    headers,
    ...rows.map((row) => columns.map((key) => (numericColumns.has(key) ? n(row[key]) : row[key]))),
  ];
  const endRow = matrix.length + 3;
  const endCol = col(columns.length - 1);
  sheet.getRange(`A4:${endCol}${endRow}`).values = matrix;
  sheet.tables.add(`A4:${endCol}${endRow}`, true, tableName).style = "TableStyleMedium2";
  sheet.getRange(`A4:${endCol}4`).format = {
    fill: brand.ink,
    font: { bold: true, color: brand.white, name: brand.font },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(`A5:${endCol}${endRow}`).format = {
    font: { color: "#111111", size: 10, name: brand.font },
    verticalAlignment: "center",
  };
  sheet.freezePanes.freezeRows(4);
  Object.entries(formats).forEach(([key, format]) => {
    const idx = columns.indexOf(key);
    if (idx >= 0) sheet.getRange(`${col(idx)}5:${col(idx)}${endRow}`).format.numberFormat = format;
  });
  return sheet;
}

async function main() {
  const metas = await readCsv("metas_positivacao_futuras.csv");
  const hist = await readCsv("historico_mensal_180d.csv");
  const resumoRfm = await readCsv("resumo_rfm.csv");
  const clientes = await readCsv("clientes_priorizados_positivacao.csv");
  const metodologia = JSON.parse(await fs.readFile(path.join(sourceDir, "metodologia_projecao.json"), "utf8"));

  const workbook = Workbook.create();
  const dash = workbook.worksheets.add("Dashboard");
  dash.showGridLines = false;
  title(dash, "A1:L1", "BUGBEE - Projecao de Positivacao CRM");
  subtitle(dash, "A2:L2", "Projecao de junho a dezembro de 2026 baseada nas metas comerciais enviadas, historico real e RFM da base. Cliente nao se repete na lista priorizada.");
  setWidths(dash, [115, 130, 125, 130, 130, 120, 80, 24, 120, 120, 120, 120]);

  const totalMeta = metas.reduce((acc, row) => acc + Number(row.meta_positivacao_clientes || 0), 0);
  const totalPriorizados = metas.reduce((acc, row) => acc + Number(row.clientes_priorizados || 0), 0);
  const totalGap = totalMeta - totalPriorizados;
  const taxaMedia = Math.round(metas.reduce((acc, row) => acc + Number(row.taxa_recompra_proj_pct || 0), 0) / metas.length);
  const poolJun = Number(metas[0]?.pool_elegivel_180d || 0);
  const ciclo = metodologia.ciclo_compra || {};

  card(dash, "A4:C6", "Meta positivacao Jun-Dez", totalMeta, brand.ink, "0");
  card(dash, "D4:F6", "Clientes priorizados unicos", totalPriorizados, brand.green, "0");
  card(dash, "H4:J6", "Gap a formar", totalGap, totalGap > 0 ? brand.orange : brand.green, "0");
  card(dash, "K4:L6", "Taxa media", taxaMedia / 100, brand.blue, "0%");
  card(dash, "A8:C10", "Pool elegivel Junho", poolJun, brand.ink2, "0");
  card(dash, "D8:F10", "Janela recompra", metodologia.janela_positivacao_dias, brand.orange, '0 "dias"');
  card(dash, "H8:J10", "Mediana intervalo", ciclo.mediana_intervalo_dias || 0, brand.gray, '0 "dias"');
  card(dash, "K8:L10", "Compras ate 180d", (ciclo.pct_ate_180d || 0) / 100, brand.green, "0%");

  dash.getRange("A12:L12").merge();
  dash.getRange("A12:L12").values = [["Projecao mensal"]];
  dash.getRange("A12:L12").format = {
    fill: brand.ink,
    font: { bold: true, color: brand.white, name: brand.font },
    horizontalAlignment: "center",
  };

  const dashRows = metas.map((row) => [
    row.mes,
    n(row.meta_pedidos),
    n(row.compradores_projetados),
    n(row.taxa_recompra_proj_pct) / 100,
    n(row.meta_positivacao_clientes),
    n(row.clientes_priorizados),
    n(row.meta_positivacao_clientes) - n(row.clientes_priorizados),
  ]);
  dash.getRange(`A14:G${14 + dashRows.length}`).values = [
    ["Mes", "Meta pedidos", "Compradores", "Taxa recompra", "Meta clientes", "Prior. unicos", "Gap"],
    ...dashRows,
  ];
  dash.getRange("A14:G14").format = {
    fill: brand.orange,
    font: { bold: true, color: brand.white, name: brand.font },
    horizontalAlignment: "center",
  };
  dash.getRange(`B15:C${14 + dashRows.length}`).format.numberFormat = "0";
  dash.getRange(`D15:D${14 + dashRows.length}`).format.numberFormat = "0%";
  dash.getRange(`E15:G${14 + dashRows.length}`).format.numberFormat = "0";
  dash.tables.add(`A14:G${14 + dashRows.length}`, true, "DashboardProjection").style = "TableStyleMedium3";

  const chartHelperRows = metas.map((row) => [
    row.mes,
    n(row.meta_positivacao_clientes),
    n(row.clientes_priorizados),
    n(row.meta_positivacao_clientes) - n(row.clientes_priorizados),
  ]);
  dash.getRange(`N14:Q${14 + chartHelperRows.length}`).values = [
    ["Mes", "Meta positivacao", "Clientes unicos", "Gap"],
    ...chartHelperRows,
  ];
  const chart = dash.charts.add("bar", dash.getRange(`N14:Q${14 + chartHelperRows.length}`));
  chart.title = "Meta vs clientes priorizados";
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis" };
  chart.yAxis = { numberFormatCode: "0" };
  chart.setPosition("I14", "L30");

  dash.getRange("A24:G24").merge();
  dash.getRange("A24:G24").values = [["Leitura executiva"]];
  dash.getRange("A24:G24").format = {
    fill: brand.ink,
    font: { bold: true, color: brand.white, name: brand.font },
    horizontalAlignment: "center",
  };
  dash.getRange("A25:G30").merge();
  dash.getRange("A25:G30").values = [[
    `A janela de 180 dias foi mantida porque ${ciclo.pct_ate_180d}% dos intervalos observados de recompra acontecem ate esse limite, com mediana de ${ciclo.mediana_intervalo_dias} dias. O RFM usa 365 dias para capturar a frequencia media de 2 a 3 compras por ano. A lista priorizada nao repete cliente: depois que um cliente entra em um mes recomendado, ele sai dos meses seguintes. O gap indica clientes que precisam ser formados por novas aquisicoes ou reativacoes antes do mes.`,
  ]];
  dash.getRange("A25:G30").format = {
    fill: brand.cream,
    font: { color: brand.ink, size: 10, name: brand.font },
    wrapText: true,
    verticalAlignment: "top",
  };
  dash.freezePanes.freezeRows(2);

  addTable(
    workbook,
    "Projecao Mensal",
    metas.map((row) => ({ ...row, gap_clientes: n(row.meta_positivacao_clientes) - n(row.clientes_priorizados) })),
    ["ano_mes", "mes", "meta_pedidos", "meta_receita_liquida", "compradores_projetados", "taxa_recompra_proj_pct", "meta_positivacao_clientes", "pool_elegivel_180d", "clientes_priorizados", "gap_clientes", "cobertura_pool_pct"],
    ["Ano mes", "Mes", "Meta pedidos", "Receita liquida", "Compradores proj.", "Taxa recompra", "Meta positivacao", "Pool 180d", "Clientes unicos", "Gap", "Cobertura pool"],
    new Set(["meta_pedidos", "meta_receita_liquida", "compradores_projetados", "taxa_recompra_proj_pct", "meta_positivacao_clientes", "pool_elegivel_180d", "clientes_priorizados", "gap_clientes", "cobertura_pool_pct"]),
    { meta_pedidos: "0", meta_receita_liquida: '"R$" 0', compradores_projetados: "0", taxa_recompra_proj_pct: '0"%"', meta_positivacao_clientes: "0", pool_elegivel_180d: "0", clientes_priorizados: "0", gap_clientes: "0", cobertura_pool_pct: '0"%"' },
    [90, 105, 105, 120, 125, 115, 130, 105, 120, 80, 115],
    "ProjecaoMensal",
  );

  addTable(
    workbook,
    "Clientes Priorizados",
    clientes,
    ["cliente_id", "mes_recomendado", "ultima_compra", "dias_no_inicio_mes", "recencia_dias", "frequencia_365d", "valor_365d", "score_recencia", "score_frequencia", "score_valor", "score_rfm", "segmento_rfm"],
    ["Cliente ID", "Mes recomendado", "Ultima compra", "Dias no mes", "Recencia", "Freq. 365d", "Valor 365d", "Score R", "Score F", "Score V", "Score RFM", "Segmento"],
    new Set(["dias_no_inicio_mes", "recencia_dias", "frequencia_365d", "valor_365d", "score_recencia", "score_frequencia", "score_valor", "score_rfm"]),
    { dias_no_inicio_mes: "0", recencia_dias: "0", frequencia_365d: "0", valor_365d: '"R$" 0', score_recencia: "0", score_frequencia: "0", score_valor: "0", score_rfm: "0" },
    [110, 120, 115, 105, 85, 90, 110, 75, 75, 75, 80, 130],
    "ClientesPriorizados",
  );

  addTable(
    workbook,
    "Resumo RFM",
    resumoRfm,
    ["segmento_rfm", "clientes", "recencia_media", "frequencia_media_365d", "valor_medio_365d", "score_medio"],
    ["Segmento", "Clientes", "Recencia media", "Freq. media 365d", "Valor medio 365d", "Score medio"],
    new Set(["clientes", "recencia_media", "frequencia_media_365d", "valor_medio_365d", "score_medio"]),
    { clientes: "0", recencia_media: '0 "dias"', frequencia_media_365d: "0", valor_medio_365d: '"R$" 0', score_medio: "0" },
    [160, 100, 125, 130, 135, 105],
    "ResumoRFM",
  );

  addTable(
    workbook,
    "Historico 180d",
    hist,
    ["ano_mes", "total_pedidos", "compradores_unicos", "recompradores", "novos_clientes", "taxa_recompra", "receita_total", "receita_recompradores", "ticket_medio_recompradores", "ticket_medio_novos"],
    ["Ano mes", "Pedidos", "Compradores", "Recompradores 180d", "Nao positivados", "Taxa recompra", "Receita total", "Receita recompra", "Ticket recompra", "Ticket nao pos."],
    new Set(["total_pedidos", "compradores_unicos", "recompradores", "novos_clientes", "taxa_recompra", "receita_total", "receita_recompradores", "ticket_medio_recompradores", "ticket_medio_novos"]),
    { total_pedidos: "0", compradores_unicos: "0", recompradores: "0", novos_clientes: "0", taxa_recompra: '0"%"', receita_total: '"R$" 0', receita_recompradores: '"R$" 0', ticket_medio_recompradores: '"R$" 0', ticket_medio_novos: '"R$" 0' },
    [90, 90, 105, 130, 115, 105, 120, 130, 125, 125],
    "Historico180d",
  );

  const fonte = workbook.worksheets.add("Fonte Metas");
  fonte.showGridLines = false;
  title(fonte, "A1:D1", "Fonte das metas enviadas");
  subtitle(fonte, "A2:D2", "O zip enviado continha fontes e PDF de fonte, nao uma planilha editavel. As metas abaixo foram transcritas da imagem enviada no chat.");
  fonte.getRange("A4:D11").values = [
    ["Ano mes", "Mes", "Meta pedidos", "Receita liquida"],
    ...metas.map((row) => [row.ano_mes, row.mes, n(row.meta_pedidos), n(row.meta_receita_liquida)]),
  ];
  fonte.getRange("A4:D4").format = { fill: brand.ink, font: { bold: true, color: brand.white, name: brand.font }, horizontalAlignment: "center" };
  fonte.getRange("C5:C11").format.numberFormat = "0";
  fonte.getRange("D5:D11").format.numberFormat = '"R$" 0';
  fonte.tables.add("A4:D11", true, "FonteMetas").style = "TableStyleMedium3";
  setWidths(fonte, [90, 110, 110, 125]);

  const met = workbook.worksheets.add("Metodologia");
  met.showGridLines = false;
  title(met, "A1:H1", "Metodologia");
  const lines = [
    ["Janela de positivacao", `${metodologia.janela_positivacao_dias} dias. Cliente so conta como recompra se voltar dentro desse recorte.`],
    ["Periodo RFM", `${metodologia.periodo_rfm_dias} dias, porque a frequencia media esperada e de 2 a 3 compras por ano.`],
    ["Cliente unico", metodologia.criterio_cliente_unico],
    ["Ciclo observado", `Mediana de ${ciclo.mediana_intervalo_dias} dias, media de ${ciclo.media_intervalo_dias} dias e ${ciclo.pct_ate_180d}% das recompras ate 180 dias.`],
    ["Projecao", "Compradores projetados vieram da meta de pedidos multiplicada pela relacao historica compradores/pedidos por mes."],
    ["Taxa de recompra", "Taxa projetada combina sazonalidade historica do mes com media dos ultimos 12 meses."],
    ["Gap", "Diferenca entre meta de positivacao e clientes unicos priorizados na base atual. Esse volume precisa ser criado por novas aquisicoes, nutricao ou reativacao."],
  ];
  met.getRange(`A3:B${lines.length + 2}`).values = lines;
  met.getRange("A3:A9").format = { fill: brand.orange, font: { bold: true, color: brand.white, name: brand.font }, verticalAlignment: "top" };
  met.getRange("B3:B9").format = { fill: brand.cream, font: { color: brand.ink, name: brand.font }, wrapText: true, verticalAlignment: "top" };
  setWidths(met, [180, 760]);
  met.getRange("A3:B9").format.rowHeightPx = 54;

  await fs.mkdir(outputDir, { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });
  for (const [sheetName, fileName, range] of [
    ["Dashboard", "dashboard.png", "A1:L32"],
    ["Projecao Mensal", "projecao_mensal.png", "A1:K16"],
    ["Clientes Priorizados", "clientes_priorizados.png", "A1:L28"],
    ["Resumo RFM", "resumo_rfm.png", "A1:F14"],
    ["Metodologia", "metodologia.png", "A1:B11"],
  ]) {
    const png = await workbook.render({ sheetName, range, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await png.arrayBuffer()));
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 },
    summary: "formula errors",
  });
  console.log(errors.ndjson);
  const check = await workbook.inspect({
    kind: "table",
    range: "Dashboard!A1:L12",
    include: "values,formulas",
    tableMaxRows: 12,
    tableMaxCols: 12,
    maxChars: 4000,
  });
  console.log(check.ndjson);
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  console.log(outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
