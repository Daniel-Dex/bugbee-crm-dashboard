import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const inputPath = path.join(root, "outputs", "outlet_stock", "outlet_stock_report_data.json");
const invernoInputPath = path.join(root, "outputs", "outlet_stock", "inverno_2026_scenarios_data.json");
const outputDir = path.join(root, "outputs", "outlet_stock");
const outputPath = path.join(outputDir, "relatorio_estoque_outlet_jun_jul_2026.xlsx");

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const rows = payload.rows;
const summary = payload.summary;
let invernoPayload = null;
try {
  invernoPayload = JSON.parse(await fs.readFile(invernoInputPath, "utf8"));
} catch {
  invernoPayload = null;
}

const moneyFmt = 'R$ #,##0.00';
const intFmt = '#,##0';
const pctFmt = '0.0%';
const numFmt = '#,##0.00';
const brandGreen = "#627B52";
const brandDarkGreen = "#49663D";
const brandCream = "#F3E7D9";
const brandBlack = "#1D1D1B";
const brandPeach = "#E6B185";
const headerFill = brandDarkGreen;
const accentFill = brandCream;
const warningFill = "#F8E1CF";
const greenFill = "#E8EFE3";

function col(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function groupByField(field) {
  const map = new Map();
  for (const row of rows) {
    const key = row[field] || "Sem informação";
    const item = map.get(key) || { nome: key, skus: 0, pecas: 0, valor: 0, precoCheioTotal: 0 };
    item.skus += 1;
    item.pecas += Number(row["Estoque Disponível"] || 0);
    item.valor += Number(row["Valor Potencial c/ Desc."] || 0);
    item.precoCheioTotal += Number(row["Preço Cheio Regra"] || 0) * Number(row["Estoque Disponível"] || 0);
    map.set(key, item);
  }
  return [...map.values()]
    .map((item) => ({
      ...item,
      precoMedioDesc: item.pecas ? item.valor / item.pecas : 0,
      precoCheioMedio: item.pecas ? item.precoCheioTotal / item.pecas : 0,
      cobertura: summary.meta_receita_junho_julho ? item.valor / summary.meta_receita_junho_julho : 0,
    }))
    .sort((a, b) => b.valor - a.valor);
}

function setColumnWidths(sheet, widths) {
  widths.forEach((width, idx) => {
    sheet.getRange(`${col(idx + 1)}:${col(idx + 1)}`).format.columnWidthPx = width;
  });
}

function styleHeader(range) {
  range.format = {
    fill: headerFill,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
}

function styleTitle(range) {
  range.format = {
    fill: brandCream,
    font: { bold: true, size: 16, color: brandDarkGreen, name: "Montserrat" },
  };
}

function writePlainTable(sheet, startRow, startCol, headers, tableRows, tableName) {
  sheet.getRangeByIndexes(startRow, startCol, 1, headers.length).values = [headers];
  if (tableRows.length) {
    sheet.getRangeByIndexes(startRow + 1, startCol, tableRows.length, headers.length).values = tableRows.map((row) =>
      headers.map((header) => row[header] ?? null),
    );
  }
  styleHeader(sheet.getRangeByIndexes(startRow, startCol, 1, headers.length));
  sheet.tables.add(`${col(startCol + 1)}${startRow + 1}:${col(startCol + headers.length)}${startRow + tableRows.length + 1}`, true, tableName);
}

const workbook = Workbook.create();
const analysis = workbook.worksheets.add("Análise");
const detail = workbook.worksheets.add("Estoque Outlet");
const byCollection = workbook.worksheets.add("Por Coleção");
const byLine = workbook.worksheets.add("Por Linha");
const assumptions = workbook.worksheets.add("Premissas");
const scenarioSheet = invernoPayload ? workbook.worksheets.add("Cenários Inverno") : null;
const invernoDetail = invernoPayload ? workbook.worksheets.add("Inverno 2026 API") : null;

for (const sheet of [analysis, detail, byCollection, byLine, assumptions, scenarioSheet, invernoDetail].filter(Boolean)) {
  sheet.showGridLines = false;
}

assumptions.getRange("A1:B10").values = [
  ["Premissa", "Valor"],
  ["Meta de receita Junho + Julho", summary.meta_receita_junho_julho],
  ["Desconto médio", 0.55],
  ["Cobertura promocional estoque/venda", summary.cobertura_estoque_objetivo],
  ["Consulta API", summary.data_consulta],
  ["Critérios", "SKU filho, ativo, estoque positivo, coleção ID 5, linha ID 7, outlet ID 9 = Sim"],
  ["Regra de preço cheio", "SE(Preço Antigo=0; Preço Venda; Preço Antigo)"],
  ["Regra de desconto", summary.observacao_desconto],
  ["Observação preço", summary.observacao_preco_api],
  ["SKUs candidatos consultados", summary.skus_candidatos_ativos_estoque_positivo],
];
styleHeader(assumptions.getRange("A1:B1"));
assumptions.getRange("B2").format.numberFormat = moneyFmt;
assumptions.getRange("B3").format.numberFormat = pctFmt;
assumptions.getRange("B4").format.numberFormat = numFmt;
assumptions.getRange("B10").format.numberFormat = intFmt;
assumptions.getRange("B2").setNumberFormat(moneyFmt);
assumptions.getRange("B3").setNumberFormat(pctFmt);
assumptions.getRange("B4").setNumberFormat(numFmt);
assumptions.getRange("B10").setNumberFormat(intFmt);
setColumnWidths(assumptions, [260, 760]);
assumptions.getRange("A1:B10").format.wrapText = true;
assumptions.freezePanes.freezeRows(1);

if (invernoPayload && scenarioSheet && invernoDetail) {
  const invernoSummary = invernoPayload.summary;
  const scenarioRows = invernoPayload.scenarios || [];
  const invernoRows = invernoPayload.rows || [];

  scenarioSheet.getRange("A1").values = [["Cenários com Inverno 2026 no mix"]];
  styleTitle(scenarioSheet.getRange("A1"));
  scenarioSheet.getRange("A3:B13").values = [
    ["Indicador", "Valor"],
    ["Coleção consultada", invernoSummary.colecao],
    ["SKUs ativos com estoque positivo", invernoSummary.skus_ativos_estoque_positivo],
    ["Peças disponíveis", invernoSummary.pecas_disponiveis],
    ["PM estimado informado", invernoSummary.pm_estimado_usuario],
    ["PM cheio medido", invernoSummary.preco_medio_cheio_ponderado],
    ["PM atual API", invernoSummary.preco_medio_api_atual_ponderado],
    ["Diferença vs estimativa", invernoSummary.diferenca_pm_vs_estimativa],
    ["Diferença vs estimativa %", invernoSummary.diferenca_pm_vs_estimativa_pct],
    ["Valor estoque cheio", invernoSummary.valor_estoque_cheio],
    ["Receita Inverno assumida (10%)", invernoSummary.receita_inverno_assumida_10_pct],
  ];
  styleHeader(scenarioSheet.getRange("A3:B3"));
  scenarioSheet.getRange("B5:B6").setNumberFormat(intFmt);
  scenarioSheet.getRange("B7:B10").setNumberFormat(moneyFmt);
  scenarioSheet.getRange("B11").setNumberFormat(pctFmt);
  scenarioSheet.getRange("B12:B13").setNumberFormat(moneyFmt);

  scenarioSheet.getRange("D3:K3").values = [[
    "Cenário",
    "Desconto Médio Final",
    "Desconto Inverno 2026",
    "PM Inverno Venda",
    "Peças Inverno",
    "Cobertura Inverno",
    "CPV Total Estimado",
    "CPV % Receita",
  ]];
  styleHeader(scenarioSheet.getRange("D3:K3"));
  if (scenarioRows.length) {
    scenarioSheet.getRangeByIndexes(3, 3, scenarioRows.length, 8).values = scenarioRows.map((row) => [
      row["Cenário"],
      row["Desconto Médio Final"],
      row["Desconto Inverno 2026"],
      row["PM Inverno Venda"],
      row["Peças Inverno Estimadas"],
      row["Cobertura Estoque Inverno"],
      row["CPV Total Estimado"],
      row["CPV % Receita"],
    ]);
    scenarioSheet.getRange(`E4:F${scenarioRows.length + 3}`).setNumberFormat(pctFmt);
    scenarioSheet.getRange(`G4:G${scenarioRows.length + 3}`).setNumberFormat(moneyFmt);
    scenarioSheet.getRange(`H4:I${scenarioRows.length + 3}`).setNumberFormat(numFmt);
    scenarioSheet.getRange(`J4:J${scenarioRows.length + 3}`).setNumberFormat(moneyFmt);
    scenarioSheet.getRange(`K4:K${scenarioRows.length + 3}`).setNumberFormat(pctFmt);
  }

  scenarioSheet.getRange("A15:K18").values = [
    ["Leitura", "", "", "", "", "", "", "", "", "", ""],
    [`O PM cheio medido da coleção Inverno 2026 é R$ ${invernoSummary.preco_medio_cheio_ponderado.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}, acima da estimativa de R$ ${invernoSummary.pm_estimado_usuario.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}.`, "", "", "", "", "", "", "", "", "", ""],
    [`Se 10% da receita vier de Inverno 2026 a preço cheio, o desconto médio final estimado fica em ${(scenarioRows[0]["Desconto Médio Final"] * 100).toFixed(1).replace(".", ",")}%.`, "", "", "", "", "", "", "", "", "", ""],
    [`Se essa coleção nova entrar com 25% de desconto médio, o desconto médio final sobe para ${(scenarioRows[1]["Desconto Médio Final"] * 100).toFixed(1).replace(".", ",")}%.`, "", "", "", "", "", "", "", "", "", ""],
  ];
  scenarioSheet.getRange("A15:K15").merge();
  scenarioSheet.getRange("A16:K16").merge();
  scenarioSheet.getRange("A17:K17").merge();
  scenarioSheet.getRange("A18:K18").merge();
  scenarioSheet.getRange("A15:K18").format = { fill: accentFill, wrapText: true };
  scenarioSheet.getRange("A15").format.font = { bold: true, color: "#17324D" };
  scenarioSheet.getRange("A20:K20").values = [[invernoSummary.observacao, "", "", "", "", "", "", "", "", "", ""]];
  scenarioSheet.getRange("A20:K20").merge();
  scenarioSheet.getRange("A20").format = { fill: greenFill, wrapText: true, font: { color: "#174A2A" } };
  scenarioSheet.getRange("A16:A20").format.rowHeightPx = 40;
  scenarioSheet.freezePanes.freezeRows(3);
  setColumnWidths(scenarioSheet, [260, 150, 30, 240, 130, 125, 160, 120, 125, 155, 120]);

  const invernoHeaders = [
    "SKU",
    "SKU Pai",
    "Produto",
    "Descrição Completa",
    "Cor",
    "Tamanho",
    "Coleção",
    "Linha de Produtos",
    "Estoque Disponível",
    "Custo Médio",
    "Preço API Atual",
    "Preço Cheio Regra",
    "Valor Estoque Cheio",
    "Valor Estoque 25% Desc.",
    "Custo Estoque",
    "Fonte Preço",
    "Última Atualização Estoque",
  ];
  writePlainTable(invernoDetail, 0, 0, invernoHeaders, invernoRows, "Inverno2026API");
  invernoDetail.freezePanes.freezeRows(1);
  invernoDetail.freezePanes.freezeColumns(2);
  if (invernoRows.length) {
    const lastWinterRow = invernoRows.length + 1;
    invernoDetail.getRange(`I2:I${lastWinterRow}`).setNumberFormat(intFmt);
    invernoDetail.getRange(`J2:O${lastWinterRow}`).setNumberFormat(moneyFmt);
  }
  setColumnWidths(invernoDetail, [120, 100, 240, 320, 120, 80, 150, 150, 100, 100, 115, 130, 130, 145, 115, 120, 150]);
}

const preferredDetailHeaders = [
  "SKU",
  "SKU Pai",
  "Produto",
  "Descrição Completa",
  "Cor",
  "Tamanho",
  "Coleção ID",
  "Coleção",
  "Linha ID",
  "Linha de Produtos",
  "Outlet ID",
  "Outlet",
  "Estoque Disponível",
  "Estoque Físico",
  "Reservado",
  "Depósitos",
  "Custo Médio",
  "Preço Antigo",
  "Preço Venda",
  "Preço Cheio Regra",
  "Desconto Projetado",
  "Preço c/ Desc. Projetado",
  "Valor Potencial c/ Desc.",
  "Valor Cheio Estoque",
  "Peças Necessárias no PM Atual",
  "Fonte Preço",
  "Última Atualização Estoque",
];
const extraHeaders = Object.keys(rows[0] || {}).filter((header) => !preferredDetailHeaders.includes(header));
const detailHeaders = [...preferredDetailHeaders.filter((header) => header in (rows[0] || {})), ...extraHeaders];
detail.getRangeByIndexes(0, 0, 1, detailHeaders.length).values = [detailHeaders];
if (rows.length) {
  detail.getRangeByIndexes(1, 0, rows.length, detailHeaders.length).values = rows.map((row) =>
    detailHeaders.map((header) => row[header] ?? null),
  );
}
styleHeader(detail.getRangeByIndexes(0, 0, 1, detailHeaders.length));
detail.freezePanes.freezeRows(1);
detail.freezePanes.freezeColumns(2);
detail.tables.add(`A1:${col(detailHeaders.length)}${rows.length + 1}`, true, "EstoqueOutlet");
setColumnWidths(detail, [
  120, 100, 240, 320, 120, 80, 95, 190, 85, 95, 85, 80, 100, 85, 85, 95, 100, 110, 110, 120, 120, 140, 130, 130,
  150, 150, 150,
]);
const firstDataRow = 2;
const lastDataRow = rows.length + 1;
if (rows.length) {
  detail.getRange(`M${firstDataRow}:O${lastDataRow}`).setNumberFormat(intFmt);
  detail.getRange(`Q${firstDataRow}:T${lastDataRow}`).setNumberFormat(moneyFmt);
  detail.getRange(`U${firstDataRow}:U${lastDataRow}`).setNumberFormat(pctFmt);
  detail.getRange(`V${firstDataRow}:X${lastDataRow}`).setNumberFormat(moneyFmt);
  detail.getRange(`AA${firstDataRow}:AA${lastDataRow}`).format.wrapText = true;
}

function writeGroupSheet(sheet, title, data) {
  sheet.getRange("A1").values = [[title]];
  styleTitle(sheet.getRange("A1"));
  sheet.getRange("A3:G3").values = [["Grupo", "SKUs", "Peças", "Valor c/ desc.", "% Meta", "PM c/ desc.", "Preço Cheio Médio"]];
  styleHeader(sheet.getRange("A3:G3"));
  if (data.length) {
    sheet.getRangeByIndexes(3, 0, data.length, 7).values = data.map((item) => [
      item.nome,
      item.skus,
      item.pecas,
      item.valor,
      item.cobertura,
      item.precoMedioDesc,
      item.precoCheioMedio,
    ]);
    sheet.tables.add(`A3:G${data.length + 3}`, true, title.replace(/\s+/g, ""));
    sheet.getRange(`B4:C${data.length + 3}`).setNumberFormat(intFmt);
    sheet.getRange(`D4:D${data.length + 3}`).setNumberFormat(moneyFmt);
    sheet.getRange(`E4:E${data.length + 3}`).setNumberFormat(pctFmt);
    sheet.getRange(`F4:G${data.length + 3}`).setNumberFormat(moneyFmt);
  }
  sheet.freezePanes.freezeRows(3);
  setColumnWidths(sheet, [260, 80, 90, 140, 90, 130, 140]);
}

const collectionRows = groupByField("Coleção");
const lineRows = groupByField("Linha de Produtos");
writeGroupSheet(byCollection, "Resumo por Coleção", collectionRows);
writeGroupSheet(byLine, "Resumo por Linha", lineRows);

const generalScenarioRows = [];
const discountCalcRows = [];
if (invernoPayload) {
  const scenarios = invernoPayload.scenarios || [];
  const invernoSummary = invernoPayload.summary || {};
  for (const scenario of scenarios) {
    generalScenarioRows.push({
      "Cenário": scenario["Cenário"],
      "Receita Outlet": scenario["Receita Outlet Promocional"],
      "Receita Inverno": scenario["Receita Inverno 2026"],
      "PM Inverno": scenario["PM Inverno Venda"],
      "Peças Inverno": scenario["Peças Inverno Estimadas"],
      "Desconto Médio Final": scenario["Desconto Médio Final"],
      "CPV Total": scenario["CPV Total Estimado"],
      "CPV % Receita": scenario["CPV % Receita"],
    });
  }
  if (scenarios.length >= 2) {
    const s0 = scenarios[0];
    const s1 = scenarios[1];
    const outletFullBase = s0["Peças Outlet Estimadas"] * summary.preco_cheio_medio_ponderado;
    const invernoFullBase0 = s0["Peças Inverno Estimadas"] * invernoSummary.preco_medio_cheio_ponderado;
    const invernoFullBase1 = s1["Peças Inverno Estimadas"] * invernoSummary.preco_medio_cheio_ponderado;
    discountCalcRows.push(
      {
        "Etapa": "1. Receita total",
        "Fórmula": "Meta Junho + Julho",
        "Preço cheio": s0["Receita Total"],
        "Inverno 25%": s1["Receita Total"],
      },
      {
        "Etapa": "2. Receita outlet",
        "Fórmula": "Receita total * 90%",
        "Preço cheio": s0["Receita Outlet Promocional"],
        "Inverno 25%": s1["Receita Outlet Promocional"],
      },
      {
        "Etapa": "3. Receita Inverno",
        "Fórmula": "Receita total * 10%",
        "Preço cheio": s0["Receita Inverno 2026"],
        "Inverno 25%": s1["Receita Inverno 2026"],
      },
      {
        "Etapa": "4. Peças outlet",
        "Fórmula": "Receita outlet / PM outlet venda",
        "Preço cheio": s0["Peças Outlet Estimadas"],
        "Inverno 25%": s1["Peças Outlet Estimadas"],
      },
      {
        "Etapa": "5. Peças Inverno",
        "Fórmula": "Receita Inverno / PM Inverno venda",
        "Preço cheio": s0["Peças Inverno Estimadas"],
        "Inverno 25%": s1["Peças Inverno Estimadas"],
      },
      {
        "Etapa": "6. Base cheia outlet",
        "Fórmula": "Peças outlet * PM cheio outlet",
        "Preço cheio": outletFullBase,
        "Inverno 25%": outletFullBase,
      },
      {
        "Etapa": "7. Base cheia Inverno",
        "Fórmula": "Peças Inverno * PM cheio Inverno",
        "Preço cheio": invernoFullBase0,
        "Inverno 25%": invernoFullBase1,
      },
      {
        "Etapa": "8. Desconto médio final",
        "Fórmula": "1 - Receita total / (Base cheia outlet + Base cheia Inverno)",
        "Preço cheio": s0["Desconto Médio Final"],
        "Inverno 25%": s1["Desconto Médio Final"],
      },
      {
        "Etapa": "9. CPV estimado",
        "Fórmula": "(Peças outlet * custo médio outlet) + (Peças Inverno * custo médio Inverno)",
        "Preço cheio": s0["CPV Total Estimado"],
        "Inverno 25%": s1["CPV Total Estimado"],
      },
    );
  }
}

analysis.getRange("A1").values = [["Análise de estoque outlet para Junho + Julho"]];
styleTitle(analysis.getRange("A1"));
analysis.getRange("A3:B14").values = [
  ["Indicador", "Valor"],
  ["SKUs outlet ativos com estoque positivo", null],
  ["Peças outlet disponíveis", null],
  ["Valor potencial com desconto projetado", null],
  ["Cobertura da meta", null],
  ["Preço cheio médio ponderado", null],
  ["Preço médio com desconto projetado", null],
  ["Peças a vender para bater a meta", null],
  ["Peças necessárias com cobertura 1,5:1", null],
  ["Cobertura atual estoque/venda", null],
  ["Peças adicionais necessárias", null],
  ["SKUs sem preço", summary.skus_sem_preco],
];
styleHeader(analysis.getRange("A3:B3"));
analysis.getRange("B4:B14").formulas = [
  [`=COUNTA('Estoque Outlet'!A2:A${lastDataRow})`],
  [`=SUM('Estoque Outlet'!M2:M${lastDataRow})`],
  [`=SUM('Estoque Outlet'!W2:W${lastDataRow})`],
  ["=B6/Premissas!B2"],
  [`=SUMPRODUCT('Estoque Outlet'!T2:T${lastDataRow},'Estoque Outlet'!M2:M${lastDataRow})/B5`],
  ["=B6/B5"],
  ["=Premissas!B2/B9"],
  ["=B10*Premissas!B4"],
  ["=B5/B10"],
  ["=MAX(0,B11-B5)"],
  [summary.skus_sem_preco],
];
analysis.getRange("B4:B5").setNumberFormat(intFmt);
analysis.getRange("B6").setNumberFormat(moneyFmt);
analysis.getRange("B7").setNumberFormat(pctFmt);
analysis.getRange("B8:B9").setNumberFormat(moneyFmt);
analysis.getRange("B10:B11").setNumberFormat(numFmt);
analysis.getRange("B12").setNumberFormat(numFmt);
analysis.getRange("B13:B14").setNumberFormat(intFmt);
analysis.getRange("A16:D19").values = [
  ["Leitura executiva", "", "", ""],
  [`Com o desconto ajustado por coleção, a receita potencial estimada cobre ${(summary.cobertura_meta * 100).toFixed(1).replace(".", ",")}% da meta de R$ 1,367 mi para Junho + Julho.`, "", "", ""],
  [`Com cobertura promocional de 1,5:1, são necessárias ${Math.round(summary.pecas_necessarias_com_cobertura).toLocaleString("pt-BR")} peças em estoque para vender ${Math.round(summary.pecas_necessarias_para_vender_meta).toLocaleString("pt-BR")} peças.`, "", "", ""],
  [`O preço médio projetado com o mix de descontos fica em torno de R$ ${summary.preco_medio_com_desc_projetado.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} por peça.`, "", "", ""],
];
analysis.getRange("A16:D16").merge();
analysis.getRange("A17:D17").merge();
analysis.getRange("A18:D18").merge();
analysis.getRange("A19:D19").merge();
analysis.getRange("A16:D19").format = { fill: accentFill, wrapText: true };
analysis.getRange("A16").format.font = { bold: true, color: "#17324D" };
analysis.getRange("A18").format = { fill: warningFill, wrapText: true };
analysis.getRange("A20:D20").values = [["Observação: Verão 2026 foi recalculado com 35% de desconto médio; demais coleções seguem com 55%. O endpoint de itens da tabela de preço retornou 403; os preços vieram das tabelas locais exportadas do Magazord.", "", "", ""]];
analysis.getRange("A20:D20").merge();
analysis.getRange("A20").format = { fill: greenFill, wrapText: true, font: { color: "#174A2A" } };
analysis.getRange("A17:A18").format.rowHeightPx = 46;
analysis.getRange("A19").format.rowHeightPx = 58;
analysis.getRange("A20").format.rowHeightPx = 62;

if (invernoPayload && generalScenarioRows.length) {
  analysis.getRange("F1").values = [["Racional geral com Inverno 2026"]];
  styleTitle(analysis.getRange("F1"));
  const scenarioHeaders = ["Cenário", "Receita Outlet", "Receita Inverno", "PM Inverno", "Peças Inverno", "Desconto Médio Final", "CPV Total", "CPV % Receita"];
  analysis.getRange("F3:M3").values = [scenarioHeaders];
  styleHeader(analysis.getRange("F3:M3"));
  analysis.getRangeByIndexes(3, 5, generalScenarioRows.length, scenarioHeaders.length).values = generalScenarioRows.map((row) =>
    scenarioHeaders.map((header) => row[header] ?? null),
  );
  analysis.getRange(`G4:H${generalScenarioRows.length + 3}`).setNumberFormat(moneyFmt);
  analysis.getRange(`I4:I${generalScenarioRows.length + 3}`).setNumberFormat(moneyFmt);
  analysis.getRange(`J4:J${generalScenarioRows.length + 3}`).setNumberFormat(numFmt);
  analysis.getRange(`K4:K${generalScenarioRows.length + 3}`).setNumberFormat(pctFmt);
  analysis.getRange(`L4:L${generalScenarioRows.length + 3}`).setNumberFormat(moneyFmt);
  analysis.getRange(`M4:M${generalScenarioRows.length + 3}`).setNumberFormat(pctFmt);

  analysis.getRange("F7").values = [["Cálculo do desconto médio"]];
  analysis.getRange("F7:M7").merge();
  analysis.getRange("F7").format = { fill: brandPeach, font: { bold: true, color: brandBlack }, wrapText: true };
  const calcHeaders = ["Etapa", "Fórmula", "Preço cheio", "Inverno 25%"];
  analysis.getRange("F8:I8").values = [calcHeaders];
  styleHeader(analysis.getRange("F8:I8"));
  analysis.getRangeByIndexes(8, 5, discountCalcRows.length, calcHeaders.length).values = discountCalcRows.map((row) =>
    calcHeaders.map((header) => row[header] ?? null),
  );
  analysis.getRange(`F9:G${discountCalcRows.length + 8}`).format.wrapText = true;
  analysis.getRange(`H9:I11`).setNumberFormat(moneyFmt);
  analysis.getRange(`H12:I13`).setNumberFormat(numFmt);
  analysis.getRange(`H14:I15`).setNumberFormat(moneyFmt);
  analysis.getRange(`H16:I16`).setNumberFormat(pctFmt);
  analysis.getRange(`H17:I17`).setNumberFormat(moneyFmt);
  analysis.getRange("F19:M20").values = [
    ["Leitura do PM Inverno", "", "", "", "", "", "", ""],
    [`PM medido da coleção Inverno 2026: R$ ${invernoPayload.summary.preco_medio_cheio_ponderado.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}. Sua estimativa de R$ 196,00 está ${(invernoPayload.summary.diferenca_pm_vs_estimativa_pct * 100).toFixed(1).replace(".", ",")}% abaixo do preço cheio medido.`, "", "", "", "", "", "", ""],
  ];
  analysis.getRange("F19:M19").merge();
  analysis.getRange("F20:M20").merge();
  analysis.getRange("F19:M20").format = { fill: greenFill, wrapText: true };
  analysis.getRange("F19").format.font = { bold: true, color: brandDarkGreen };
  analysis.getRange("F9:F17").format.fill = "#FBF7F1";
} else {
  analysis.getRange("F3:H13").values = [
    ["Coleção", "Peças", "Valor c/ desc."],
    ...collectionRows.slice(0, 10).map((item) => [item.nome, item.pecas, item.valor]),
  ];
  styleHeader(analysis.getRange("F3:H3"));
  analysis.getRange("G4:G13").setNumberFormat(intFmt);
  analysis.getRange("H4:H13").setNumberFormat(moneyFmt);
}
setColumnWidths(analysis, [280, 150, 40, 40, 30, 230, 300, 140, 140, 110, 120, 140, 110]);

const preview1 = await workbook.render({ sheetName: "Análise", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "preview_analise.png"), new Uint8Array(await preview1.arrayBuffer()));
const preview2 = await workbook.render({ sheetName: "Estoque Outlet", range: "A1:Z25", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "preview_estoque.png"), new Uint8Array(await preview2.arrayBuffer()));
if (invernoPayload) {
  const preview3 = await workbook.render({ sheetName: "Cenários Inverno", autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, "preview_cenarios_inverno.png"), new Uint8Array(await preview3.arrayBuffer()));
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
