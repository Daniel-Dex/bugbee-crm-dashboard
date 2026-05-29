import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const outputDir = path.join(root, "outputs", "julho_2025_mais_vendidos");
const inputPath = path.join(outputDir, "julho_2025_mais_vendidos_data.json");
const outputPath = path.join(outputDir, "relatorio_produtos_mais_vendidos_julho_2025.xlsx");
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));

const moneyFmt = 'R$ #,##0.00';
const intFmt = '#,##0';
const pctFmt = '0.0%';
const headerFill = "#17324D";
const accentFill = "#EAF2F8";

function col(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function styleHeader(range) {
  range.format = {
    fill: headerFill,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
}

function setColumnWidths(sheet, widths) {
  widths.forEach((width, idx) => {
    sheet.getRange(`${col(idx + 1)}:${col(idx + 1)}`).format.columnWidthPx = width;
  });
}

function writeTable(sheet, headers, rows, tableName) {
  sheet.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
  if (rows.length) {
    sheet.getRangeByIndexes(1, 0, rows.length, headers.length).values = rows.map((row) =>
      headers.map((header) => row[header] ?? null),
    );
  }
  styleHeader(sheet.getRangeByIndexes(0, 0, 1, headers.length));
  sheet.tables.add(`A1:${col(headers.length)}${rows.length + 1}`, true, tableName);
  sheet.freezePanes.freezeRows(1);
}

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Resumo");
const productsSheet = workbook.worksheets.add("Mais Vendidos");
const skuSheet = workbook.worksheets.add("Detalhe SKU");
const collectionSheet = workbook.worksheets.add("Por Coleção");
const assumptionsSheet = workbook.worksheets.add("Premissas");

for (const sheet of [summarySheet, productsSheet, skuSheet, collectionSheet, assumptionsSheet]) {
  sheet.showGridLines = false;
}

summarySheet.getRange("A1").values = [["Produtos mais vendidos em Julho/2025"]];
summarySheet.getRange("A1").format = { font: { bold: true, size: 16, color: "#17324D" } };
summarySheet.getRange("A3:B9").values = [
  ["Indicador", "Valor"],
  ["Peças vendidas", payload.summary.quantidade_total],
  ["Referências vendidas", payload.summary.produtos_referencias],
  ["Faturamento vendido", payload.summary.valor_vendido_total],
  ["Preço cheio total", payload.summary.preco_cheio_total],
  ["Desconto médio vendido", payload.summary.desconto_medio],
  ["Linhas com fallback Preço Venda", payload.summary.linhas_com_fallback_preco_venda],
];
styleHeader(summarySheet.getRange("A3:B3"));
summarySheet.getRange("B4:B5").setNumberFormat(intFmt);
summarySheet.getRange("B6:B7").setNumberFormat(moneyFmt);
summarySheet.getRange("B8").setNumberFormat(pctFmt);
summarySheet.getRange("B9").setNumberFormat(intFmt);

summarySheet.getRange("D3:H13").values = [
  ["Ranking", "Referência", "Produto", "Coleção", "Peças"],
  ...payload.products.slice(0, 10).map((row, idx) => [
    idx + 1,
    row["Referência"],
    row["Produto"],
    row["Coleção"],
    row["Quantidade Vendida"],
  ]),
];
styleHeader(summarySheet.getRange("D3:H3"));
summarySheet.getRange("H4:H13").setNumberFormat(intFmt);
summarySheet.getRange("A11:H14").values = [
  ["Leitura", "", "", "", "", "", "", ""],
  ["O ranking está ordenado por peças vendidas, somando as variações de SKU dentro da mesma referência/produto/coleção.", "", "", "", "", "", "", ""],
  ["O desconto vendido foi recalculado como 1 - Valor Vendido / Preço Cheio Total, preservando a regra Preço Antigo; se zerado, Preço Venda.", "", "", "", "", "", "", ""],
  ["A aba Detalhe SKU permite auditar preço antigo, preço vendido e desconto linha a linha.", "", "", "", "", "", "", ""],
];
summarySheet.getRange("A11:H11").merge();
summarySheet.getRange("A12:H12").merge();
summarySheet.getRange("A13:H13").merge();
summarySheet.getRange("A14:H14").merge();
summarySheet.getRange("A11:H14").format = { fill: accentFill, wrapText: true };
summarySheet.getRange("A11").format.font = { bold: true, color: "#17324D" };
setColumnWidths(summarySheet, [220, 140, 30, 80, 100, 280, 180, 80]);

const productHeaders = [
  "Referência",
  "Produto",
  "Coleção",
  "Categoria Principal",
  "Quantidade Vendida",
  "Valor Vendido",
  "Preço Cheio Total",
  "Preço Médio Vendido",
  "Preço Cheio Médio",
  "Desconto Vendido",
  "SKUs Vendidos",
];
writeTable(productsSheet, productHeaders, payload.products, "ProdutosMaisVendidos");
productsSheet.getRange(`E2:E${payload.products.length + 1}`).setNumberFormat(intFmt);
productsSheet.getRange(`F2:I${payload.products.length + 1}`).setNumberFormat(moneyFmt);
productsSheet.getRange(`J2:J${payload.products.length + 1}`).setNumberFormat(pctFmt);
productsSheet.getRange(`K2:K${payload.products.length + 1}`).setNumberFormat(intFmt);
setColumnWidths(productsSheet, [110, 330, 180, 160, 100, 130, 130, 130, 130, 100, 95]);
productsSheet.freezePanes.freezeColumns(2);

const detailHeaders = [
  "SKU",
  "Referência",
  "Produto",
  "Coleção",
  "Categoria",
  "Quantidade Vendida",
  "Valor Vendido",
  "Preço Venda Unit.",
  "Preço Antigo",
  "Preço Cheio Regra",
  "Preço Cheio Total",
  "Desconto Vendido",
  "Fonte Preço",
];
writeTable(skuSheet, detailHeaders, payload.details, "DetalheSKU");
skuSheet.getRange(`F2:F${payload.details.length + 1}`).setNumberFormat(intFmt);
skuSheet.getRange(`G2:K${payload.details.length + 1}`).setNumberFormat(moneyFmt);
skuSheet.getRange(`L2:L${payload.details.length + 1}`).setNumberFormat(pctFmt);
setColumnWidths(skuSheet, [120, 100, 320, 180, 150, 95, 120, 120, 110, 130, 130, 100, 160]);
skuSheet.freezePanes.freezeColumns(2);

const collectionHeaders = ["Coleção", "Produtos", "Quantidade Vendida", "Valor Vendido", "Preço Cheio Total", "Desconto Vendido"];
writeTable(collectionSheet, collectionHeaders, payload.collections, "ResumoColecao");
collectionSheet.getRange(`B2:C${payload.collections.length + 1}`).setNumberFormat(intFmt);
collectionSheet.getRange(`D2:E${payload.collections.length + 1}`).setNumberFormat(moneyFmt);
collectionSheet.getRange(`F2:F${payload.collections.length + 1}`).setNumberFormat(pctFmt);
setColumnWidths(collectionSheet, [220, 90, 120, 130, 130, 110]);

assumptionsSheet.getRange("A1:B7").values = [
  ["Campo", "Valor"],
  ["Período", payload.summary.periodo],
  ["Fonte", payload.summary.fonte],
  ["Regra de desconto", payload.summary.regra_desconto],
  ["Agrupamento", "Referência + Produto + Coleção"],
  ["Ordenação", "Quantidade vendida desc.; Valor vendido desc."],
  ["Gerado em", payload.summary.data_geracao],
];
styleHeader(assumptionsSheet.getRange("A1:B1"));
assumptionsSheet.getRange("A1:B7").format.wrapText = true;
setColumnWidths(assumptionsSheet, [180, 760]);

const preview = await workbook.render({ sheetName: "Resumo", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "preview_resumo.png"), new Uint8Array(await preview.arrayBuffer()));

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
