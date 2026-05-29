from __future__ import annotations

import argparse
import shutil
from dataclasses import asdict
from pathlib import Path

from .config import compute_weekly_period, load_settings
from .logs import setup_logger


def available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(2, 100):
        candidate = path.with_name(f"{stem}_v{idx}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_nova{suffix}")


def rows_from_metrics(metrics, prefix="Atual") -> list[dict]:
    return [
        {"grupo": prefix, "indicador": "Faturamento bruto", "valor": metrics.faturamento_bruto},
        {"grupo": prefix, "indicador": "Devoluções", "valor": metrics.devolucoes},
        {"grupo": prefix, "indicador": "Faturamento líquido", "valor": metrics.faturamento_liquido},
        {"grupo": prefix, "indicador": "Pedidos", "valor": metrics.pedidos},
        {"grupo": prefix, "indicador": "Pedidos site", "valor": metrics.pedidos_site},
        {"grupo": prefix, "indicador": "Pedidos marketplace", "valor": metrics.pedidos_marketplace},
        {"grupo": prefix, "indicador": "Receita site", "valor": metrics.receita_site},
        {"grupo": prefix, "indicador": "Receita marketplace", "valor": metrics.receita_marketplace},
        {"grupo": prefix, "indicador": "Itens vendidos", "valor": metrics.itens_vendidos},
        {"grupo": prefix, "indicador": "Ticket médio", "valor": metrics.ticket_medio},
        {"grupo": prefix, "indicador": "Peças por pedido", "valor": metrics.pecas_por_pedido},
        {"grupo": prefix, "indicador": "Venda preço cheio total", "valor": metrics.venda_preco_cheio_total},
        {"grupo": prefix, "indicador": "Valor de venda total", "valor": metrics.valor_venda_total},
        {"grupo": prefix, "indicador": "Desconto médio", "valor": metrics.desconto_medio},
        {"grupo": prefix, "indicador": "Clientes", "valor": metrics.clientes},
    ]


def run(require_credentials: bool = True) -> dict:
    settings = load_settings(require_credentials=require_credentials)
    period = compute_weekly_period()
    log_path = settings.logs_dir / f"log_execucao_{period.current_end.isoformat()}.txt"
    logger = setup_logger(log_path)
    logger.info("Início da execução semanal Bugbee")
    logger.info("Período analisado: %s", period.label)

    from .calculations import calculate_weekly_metrics, compare, rank_by
    from .extract import extract_magazord, extract_product_characteristics
    from .history import save_history
    from .presentation_generator import generate_presentation
    from .reference_data import load_reference_lookup
    from .spreadsheet_updater import build_weekly_workbook
    from .transform import (
        build_category_lookup,
        build_category_details,
        build_characteristic_lookup,
        build_price_lookup,
        build_product_lookup_with_categories,
        enrich_items,
        flatten_items_from_invoices,
        flatten_items_from_orders,
        money,
        normalize_orders,
        normalize_stock,
    )

    for path in [settings.raw_dir, settings.processed_dir, settings.history_dir, settings.output_dir, settings.template_dir]:
        path.mkdir(parents=True, exist_ok=True)

    raw = extract_magazord(settings, period, logger)
    orders = normalize_orders(raw.get("pedidos", []))
    previous_orders = normalize_orders(raw.get("pedidos_semana_anterior", []))
    yoy_orders = normalize_orders(raw.get("pedidos_ano_anterior", []))

    order_items = flatten_items_from_orders(raw.get("pedidos", []))
    previous_order_items = flatten_items_from_orders(raw.get("pedidos_semana_anterior", []))
    yoy_order_items = flatten_items_from_orders(raw.get("pedidos_ano_anterior", []))
    invoice_items_saida = flatten_items_from_invoices(raw.get("notas_fiscais", []))
    invoice_items_entrada = flatten_items_from_invoices(raw.get("notas_fiscais_entrada", []))
    stock = normalize_stock(raw.get("estoque", []))

    category_lookup = build_category_lookup(raw.get("categorias", []))
    category_details = build_category_details(raw.get("categorias", []))
    product_lookup = build_product_lookup_with_categories(raw.get("produtos", []), category_lookup, category_details)
    price_lookup = build_price_lookup(raw.get("itens_tabela_preco", []))
    reference_lookup = load_reference_lookup()

    preliminary_items = invoice_items_saida or order_items
    preliminary_sold_qty_by_sku = {}
    for item in preliminary_items:
        sku = str(item.get("sku") or "")
        preliminary_sold_qty_by_sku[sku] = preliminary_sold_qty_by_sku.get(sku, 0) + money(item.get("quantidade"))
    relevant_parent_skus = {
        str((product_lookup.get(str(item.get("sku") or "")) or {}).get("sku_pai") or item.get("sku_pai") or item.get("sku") or "")
        for item in preliminary_items
        if item.get("sku_pai") or item.get("sku")
    }
    for row in stock:
        sku = str(row.get("sku") or "")
        if money(row.get("quantidade_disponivel") or row.get("quantidade_fisica")) > 0:
            product_info = product_lookup.get(sku) or {}
            relevant_parent_skus.add(str(product_info.get("sku_pai") or row.get("sku_pai") or sku))
    product_characteristics = extract_product_characteristics(settings, period, sorted(relevant_parent_skus), logger)
    characteristic_lookup = build_characteristic_lookup(product_characteristics)

    order_item_lookup = {}
    for item in order_items + previous_order_items + yoy_order_items:
        for key in ((item.get("pedido_id"), item.get("sku")), (item.get("pedido_codigo"), item.get("sku"))):
            if key[0] and key[1]:
                order_item_lookup[(str(key[0]), str(key[1]))] = item

    def enrich_with_order_context(rows: list[dict]) -> list[dict]:
        merged = []
        for row in rows:
            item = dict(row)
            ctx = order_item_lookup.get((str(item.get("pedido_id")), str(item.get("sku"))), {})
            for key in ["origem_codigo", "origem", "marketplace_id", "marketplace_nome", "situacao_codigo", "situacao", "situacao_tipo", "categoria", "categoria_id"]:
                if item.get(key) in (None, "", 0):
                    item[key] = ctx.get(key)
            merged.append(item)
        return enrich_items(merged, product_lookup, characteristic_lookup, reference_lookup, price_lookup)

    items = enrich_with_order_context(invoice_items_saida or order_items)
    return_items = enrich_with_order_context(invoice_items_entrada)
    previous_items = enrich_with_order_context(flatten_items_from_invoices(raw.get("notas_fiscais_semana_anterior", [])) or previous_order_items)
    previous_return_items = enrich_with_order_context(flatten_items_from_invoices(raw.get("notas_fiscais_entrada_semana_anterior", [])))
    yoy_items = enrich_with_order_context(flatten_items_from_invoices(raw.get("notas_fiscais_ano_anterior", [])) or yoy_order_items)
    yoy_return_items = enrich_with_order_context(flatten_items_from_invoices(raw.get("notas_fiscais_entrada_ano_anterior", [])))

    metrics = calculate_weekly_metrics(orders, items, return_items)
    previous_metrics = calculate_weekly_metrics(previous_orders, previous_items, previous_return_items)
    yoy_metrics = calculate_weekly_metrics(yoy_orders, yoy_items, yoy_return_items)

    comparison_rows = [
        {"indicador": "Faturamento bruto", "atual": metrics.faturamento_bruto, "semana_anterior": previous_metrics.faturamento_bruto, "ano_anterior": yoy_metrics.faturamento_bruto, **compare(metrics.faturamento_bruto, previous_metrics.faturamento_bruto)},
        {"indicador": "Faturamento líquido", "atual": metrics.faturamento_liquido, "semana_anterior": previous_metrics.faturamento_liquido, "ano_anterior": yoy_metrics.faturamento_liquido, **compare(metrics.faturamento_liquido, previous_metrics.faturamento_liquido)},
        {"indicador": "Devoluções", "atual": metrics.devolucoes, "semana_anterior": previous_metrics.devolucoes, "ano_anterior": yoy_metrics.devolucoes, **compare(metrics.devolucoes, previous_metrics.devolucoes)},
        {"indicador": "Pedidos", "atual": metrics.pedidos, "semana_anterior": previous_metrics.pedidos, "ano_anterior": yoy_metrics.pedidos, **compare(metrics.pedidos, previous_metrics.pedidos)},
        {"indicador": "Ticket médio", "atual": metrics.ticket_medio, "semana_anterior": previous_metrics.ticket_medio, "ano_anterior": yoy_metrics.ticket_medio, **compare(metrics.ticket_medio, previous_metrics.ticket_medio)},
        {"indicador": "Desconto médio", "atual": metrics.desconto_medio, "semana_anterior": previous_metrics.desconto_medio, "ano_anterior": yoy_metrics.desconto_medio, **compare(metrics.desconto_medio or 0, previous_metrics.desconto_medio or 0)},
        {"indicador": "Faturamento líquido YoY", "atual": metrics.faturamento_liquido, "ano_anterior": yoy_metrics.faturamento_liquido, **compare(metrics.faturamento_liquido, yoy_metrics.faturamento_liquido)},
    ]

    product_agg = {}
    for item in items:
        key = item.get("sku") or item.get("produto")
        row = product_agg.setdefault(key, {
            "sku": item.get("sku"),
            "sku_pai": item.get("sku_pai"),
            "produto": item.get("produto"),
            "cor": item.get("cor"),
            "tamanho": item.get("tamanho"),
            "categoria": item.get("categoria"),
            "genero": item.get("genero"),
            "colecao": item.get("colecao"),
            "linha_produto": item.get("linha_produto"),
            "quantidade": 0,
            "valor_venda": 0,
            "valor_preco_cheio": 0,
        })
        row["quantidade"] += money(item.get("quantidade"))
        row["valor_venda"] += money(item.get("valor_total"))
        row["valor_preco_cheio"] += money(item.get("valor_preco_cheio_total"))
    product_rows = sorted(product_agg.values(), key=lambda x: x["valor_venda"], reverse=True)
    category_rows = rank_by(items, "valor_total", "categoria", 30)

    sold_qty_by_sku = {}
    sold_value_by_sku = {}
    full_price_by_sku = {}
    for item in items:
        sku = str(item.get("sku") or "")
        sold_qty_by_sku[sku] = sold_qty_by_sku.get(sku, 0) + money(item.get("quantidade"))
        sold_value_by_sku[sku] = sold_value_by_sku.get(sku, 0) + money(item.get("valor_total"))
        full_price_by_sku[sku] = full_price_by_sku.get(sku, 0) + money(item.get("valor_preco_cheio_total"))

    stock_rows = []
    for row in enrich_items(stock, product_lookup, characteristic_lookup, reference_lookup, price_lookup):
        sku = str(row.get("sku") or "")
        qty_stock = money(row.get("quantidade_disponivel") or row.get("quantidade_fisica"))
        qty_sold = sold_qty_by_sku.get(sku, 0)
        if qty_stock <= 0 or row.get("ativo") is False:
            continue
        stock_rows.append({
            "sku": sku,
            "produto": row.get("produto"),
            "cor": row.get("cor"),
            "tamanho": row.get("tamanho"),
            "categoria": row.get("categoria"),
            "genero": row.get("genero"),
            "quantidade_estoque": qty_stock,
            "quantidade_vendida": qty_sold,
            "quantidade_comprada": row.get("quantidade_comprada"),
            "preco_cheio_x_qtd_vendida": full_price_by_sku.get(sku, 0),
            "valor_de_venda": sold_value_by_sku.get(sku, 0),
            "custo_medio_x_4": money(row.get("custo_medio")) * 4,
            "colecao": row.get("colecao"),
            "linha_produto": row.get("linha_produto"),
        })
    stock_rows = sorted(stock_rows, key=lambda row: (money(row.get("quantidade_vendida")), money(row.get("quantidade_estoque"))), reverse=True)

    presentation_rows = rows_from_metrics(metrics)
    presentation_rows.append({"grupo": "Atual", "indicador": "Desconto médio total", "valor": metrics.desconto_medio})

    data = {
        "orders": orders,
        "items": items,
        "return_items": return_items,
        "weekly_indicator_rows": rows_from_metrics(metrics),
        "comparison_rows": comparison_rows,
        "product_category_rows": [{"tipo": "produto", **row} for row in product_rows] + [{"tipo": "categoria", **row} for row in category_rows],
        "stock_rows": stock_rows,
        "marketplace_rows": [row for row in items if row.get("origem") == "Marketplace"],
        "site_rows": [row for row in items if row.get("origem") == "Site"],
        "presentation_rows": presentation_rows,
    }

    date_tag = period.current_end.isoformat()
    xlsx_path = available_path(settings.output_dir / f"planilha_dados_semanal_bugbee_{date_tag}.xlsx")
    pptx_path = available_path(settings.output_dir / f"apresentacao_semanal_bugbee_{date_tag}.pptx")
    build_weekly_workbook(xlsx_path, data)

    insights = [
        "Faturamento bruto usa notas de saída; faturamento líquido desconta notas de entrada identificadas como devolução por CFOP.",
        "Origem de pedidos passa a vir do detalhe do pedido: Site, Marketplace, Manual ou PDV.",
        "Desconto médio é calculado por preço cheio total versus valor de venda total.",
    ]
    generate_presentation(pptx_path, period.label, asdict(metrics), insights)

    current_xlsx = settings.output_dir / "planilha_dados_semanal_bugbee_atual.xlsx"
    current_pptx = settings.output_dir / "apresentacao_semanal_bugbee_atual.pptx"
    shutil.copy2(xlsx_path, current_xlsx)
    shutil.copy2(pptx_path, current_pptx)

    history_path = settings.history_dir / f"indicadores_{date_tag}.json"
    save_history(history_path, {"period": asdict(period), "metrics": asdict(metrics), "comparison": comparison_rows})

    logger.info("Pedidos extraídos: %s", len(orders))
    logger.info("Itens extraídos: %s", len(items))
    logger.info("Itens de devolução extraídos: %s", len(return_items))
    logger.info("Itens em Estoque e Giro: %s", len(stock_rows))
    logger.info("Arquivo XLSX criado: %s", xlsx_path)
    logger.info("Arquivo PPTX criado: %s", pptx_path)
    logger.info("Fim da execução semanal Bugbee")

    return {"xlsx": str(xlsx_path), "pptx": str(pptx_path), "log": str(log_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-api", action="store_true", help="Valida estrutura sem exigir variáveis de API. Não gera dados reais.")
    args = parser.parse_args()
    if args.no_api:
        settings = load_settings(require_credentials=False)
        for path in [settings.raw_dir, settings.processed_dir, settings.history_dir, settings.output_dir, settings.template_dir, settings.logs_dir]:
            path.mkdir(parents=True, exist_ok=True)
        print("Estrutura criada. Configure MAGAZORD_BASE_URL, MAGAZORD_API_KEY e MAGAZORD_API_SECRET para executar com API.")
        return
    run(require_credentials=True)


if __name__ == "__main__":
    main()
