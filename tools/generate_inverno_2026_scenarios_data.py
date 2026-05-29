from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.magazord_client import MagazordClient
from src.reference_data import load_reference_lookup
from src.transform import money, parent_sku, pick, split_product_variant


RUN_DATE = datetime.now().strftime("%Y-%m-%d")
RAW_DIR = ROOT / "data" / "raw" / RUN_DATE
OUT_DIR = ROOT / "outputs" / "outlet_stock"
TARGET_REVENUE = 1_367_000.0
INVERNO_REVENUE_SHARE = 0.10
OUTLET_REVENUE_SHARE = 0.90
NEW_COLLECTION_DISCOUNT_SCENARIO = 0.25
USER_ESTIMATED_INVERNO_PM = 196.0
TARGET_COLLECTION = "Inverno 2026"


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key] = value


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def make_client(logger: logging.Logger) -> MagazordClient:
    return MagazordClient(
        os.environ["MAGAZORD_BASE_URL"],
        os.environ["MAGAZORD_API_KEY"],
        os.environ["MAGAZORD_API_SECRET"],
        logger,
        timeout=45,
    )


def characteristic_value(chars: list[dict[str, Any]], code: int) -> tuple[Any, Any]:
    for char in chars:
        if int(pick(char, "codigo", default=0) or 0) == code:
            return pick(char, "valor"), pick(char, "valorDescritivo", "valorDescricao", "valor")
    return None, None


def get_chars_for_sku(args: tuple[str, str, str, str]) -> dict[str, Any]:
    sku, base_url, api_key, api_secret = args
    logger = logging.getLogger(f"chars.{sku}")
    client = MagazordClient(base_url, api_key, api_secret, logger, timeout=45)
    try:
        result = client.buscar_produto_caracteristicas(sku)
        return {"sku": sku, "caracteristicas": result.rows, "erro": None}
    except Exception as exc:
        return {"sku": sku, "caracteristicas": [], "erro": str(exc)}


def get_frontend_detail(args: tuple[str, str, str, str]) -> dict[str, Any]:
    sku, base_url, api_key, api_secret = args
    logger = logging.getLogger(f"frontend.{sku}")
    client = MagazordClient(base_url, api_key, api_secret, logger, timeout=45)
    try:
        payload = client._request("GET", f"/v2/site/frontend/produto/1/{sku}")
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return {"sku": sku, "frontend": data if isinstance(data, dict) else {}, "erro": None}
    except Exception as exc:
        return {"sku": sku, "frontend": {}, "erro": str(exc)}


def main() -> None:
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("inverno_2026")
    client = make_client(logger)
    started_at = datetime.now().isoformat(timespec="seconds")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Consultando API para estoque e produtos atuais")
    stock_rows = client.buscar_estoque().rows
    products = client.buscar_produtos().rows
    save_json(RAW_DIR / "inverno_2026_estoque_api.json", stock_rows)
    save_json(RAW_DIR / "inverno_2026_produtos_api.json", products)

    active_derivations: dict[str, dict[str, Any]] = {}
    for product in products:
        product_active = bool(pick(product, "ativo"))
        parent = str(pick(product, "codigo", default="") or "")
        product_name = pick(product, "nome")
        for derivation in pick(product, "derivacoes", default=[]) or []:
            if not isinstance(derivation, dict):
                continue
            sku = str(pick(derivation, "codigo", default="") or "")
            if not sku:
                continue
            product_base, color, size = split_product_variant(pick(derivation, "nome"))
            active_derivations[sku] = {
                "sku": sku,
                "sku_pai": parent_sku(sku) or parent,
                "codigo_produto_pai": parent,
                "produto": product_base or product_name,
                "descricao_completa": pick(derivation, "nome") or product_name,
                "cor": color,
                "tamanho": size,
                "produto_pai_ativo": product_active,
                "sku_ativo": bool(pick(derivation, "ativo")),
            }

    stock_by_sku: dict[str, dict[str, Any]] = {}
    for row in stock_rows:
        sku = str(pick(row, "produto", default="") or "")
        if not sku:
            continue
        info = stock_by_sku.setdefault(
            sku,
            {
                "sku": sku,
                "quantidade_disponivel": 0.0,
                "quantidade_fisica": 0.0,
                "quantidade_reservada": 0.0,
                "depositos": set(),
                "ativo_estoque": True,
                "custo_medio_total": 0.0,
                "custo_medio_peso": 0.0,
                "descricao_estoque": pick(row, "descricaoProduto"),
                "ultima_atualizacao": pick(row, "dataHoraAtualizacao"),
            },
        )
        qty_available = money(pick(row, "quantidadeDisponivelVenda"))
        qty_physical = money(pick(row, "quantidadeFisica"))
        cost = money(pick(row, "custoMedio"))
        info["quantidade_disponivel"] += qty_available
        info["quantidade_fisica"] += qty_physical
        info["quantidade_reservada"] += money(pick(row, "quantidadeReservadoSaida"))
        info["depositos"].add(str(pick(row, "deposito", default="") or ""))
        info["ativo_estoque"] = bool(info["ativo_estoque"] and pick(row, "ativo"))
        info["custo_medio_total"] += cost * max(qty_available, 0)
        info["custo_medio_peso"] += max(qty_available, 0)
        if str(pick(row, "dataHoraAtualizacao", default="") or "") > str(info.get("ultima_atualizacao") or ""):
            info["ultima_atualizacao"] = pick(row, "dataHoraAtualizacao")

    candidate_skus = [
        sku
        for sku, stock in stock_by_sku.items()
        if stock["ativo_estoque"]
        and stock["quantidade_disponivel"] > 0
        and sku in active_derivations
        and active_derivations[sku]["produto_pai_ativo"]
        and active_derivations[sku]["sku_ativo"]
    ]
    logger.info("SKUs ativos com estoque positivo: %s", len(candidate_skus))

    char_cache_path = RAW_DIR / "inverno_2026_produto_caracteristicas_api.json"
    base_url = os.environ["MAGAZORD_BASE_URL"]
    api_key = os.environ["MAGAZORD_API_KEY"]
    api_secret = os.environ["MAGAZORD_API_SECRET"]
    char_rows = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(get_chars_for_sku, (sku, base_url, api_key, api_secret)) for sku in candidate_skus]
        for index, future in enumerate(as_completed(futures), start=1):
            char_rows.append(future.result())
            if index % 250 == 0:
                logger.info("Características consultadas: %s/%s", index, len(candidate_skus))
                save_json(char_cache_path, char_rows)
            time.sleep(0.005)
    save_json(char_cache_path, char_rows)
    char_by_sku = {str(row["sku"]): row for row in char_rows}

    inverno_skus = []
    for sku in candidate_skus:
        chars = char_by_sku.get(sku, {}).get("caracteristicas", []) or []
        collection_value, collection = characteristic_value(chars, 5)
        if str(collection or "").strip() == TARGET_COLLECTION:
            line_value, product_line = characteristic_value(chars, 7)
            inverno_skus.append((sku, collection_value, collection, line_value, product_line))
    logger.info("SKUs %s encontrados: %s", TARGET_COLLECTION, len(inverno_skus))

    frontend_cache_path = RAW_DIR / "inverno_2026_frontend_api.json"
    frontend_rows = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(get_frontend_detail, (sku, base_url, api_key, api_secret)) for sku, *_ in inverno_skus]
        for index, future in enumerate(as_completed(futures), start=1):
            frontend_rows.append(future.result())
            if index % 100 == 0:
                logger.info("Preço frontend consultado: %s/%s", index, len(inverno_skus))
                save_json(frontend_cache_path, frontend_rows)
            time.sleep(0.005)
    save_json(frontend_cache_path, frontend_rows)
    frontend_by_sku = {str(row["sku"]): row.get("frontend", {}) for row in frontend_rows}

    price_lookup = load_reference_lookup()
    detail_rows: list[dict[str, Any]] = []
    for sku, collection_value, collection, line_value, product_line in inverno_skus:
        stock = stock_by_sku[sku]
        product = active_derivations[sku]
        price_info = price_lookup.get(sku) or {}
        old_price = money(price_info.get("preco_antigo"))
        sale_price_table = money(price_info.get("preco_tabela_venda"))
        full_price = old_price if old_price > 0 else sale_price_table
        if full_price <= 0:
            full_price = money(price_info.get("preco_cheio"))
        frontend = frontend_by_sku.get(sku) or {}
        api_sale_price = money(pick(frontend, "valor"))
        api_value_de = money(pick(frontend, "valor_de"))
        api_full_price = api_value_de if api_value_de > 0 else api_sale_price
        if full_price <= 0:
            full_price = api_full_price
        qty = money(stock["quantidade_disponivel"])
        avg_cost = stock["custo_medio_total"] / stock["custo_medio_peso"] if stock["custo_medio_peso"] else 0
        detail_rows.append(
            {
                "SKU": sku,
                "SKU Pai": product.get("sku_pai"),
                "Produto": product.get("produto") or stock.get("descricao_estoque"),
                "Descrição Completa": product.get("descricao_completa") or stock.get("descricao_estoque"),
                "Cor": product.get("cor"),
                "Tamanho": product.get("tamanho"),
                "Coleção ID": collection_value,
                "Coleção": collection,
                "Linha ID": line_value,
                "Linha de Produtos": product_line,
                "Estoque Disponível": qty,
                "Estoque Físico": money(stock["quantidade_fisica"]),
                "Reservado": money(stock["quantidade_reservada"]),
                "Custo Médio": avg_cost,
                "Preço Antigo": old_price,
                "Preço Venda Tabela": sale_price_table,
                "Preço API Atual": api_sale_price,
                "Valor De API": api_value_de,
                "Preço Cheio Regra": full_price,
                "Valor Estoque Cheio": qty * full_price,
                "Valor Estoque 25% Desc.": qty * full_price * 0.75,
                "Custo Estoque": qty * avg_cost,
                "Fonte Preço": "Tabela local" if price_info else "API frontend",
                "Última Atualização Estoque": stock.get("ultima_atualizacao"),
            }
        )

    detail_rows.sort(key=lambda row: (money(row["Valor Estoque Cheio"]), money(row["Estoque Disponível"])), reverse=True)

    qty_total = sum(money(row["Estoque Disponível"]) for row in detail_rows)
    full_value_total = sum(money(row["Valor Estoque Cheio"]) for row in detail_rows)
    discount25_value_total = sum(money(row["Valor Estoque 25% Desc."]) for row in detail_rows)
    cost_total = sum(money(row["Custo Estoque"]) for row in detail_rows)
    full_pm = full_value_total / qty_total if qty_total else 0
    api_pm = sum(money(row["Preço API Atual"]) * money(row["Estoque Disponível"]) for row in detail_rows) / qty_total if qty_total else 0
    cost_pm = cost_total / qty_total if qty_total else 0

    outlet_payload = json.loads((OUT_DIR / "outlet_stock_report_data.json").read_text(encoding="utf-8"))
    outlet_summary = outlet_payload["summary"]
    outlet_revenue = TARGET_REVENUE * OUTLET_REVENUE_SHARE
    inverno_revenue = TARGET_REVENUE * INVERNO_REVENUE_SHARE
    outlet_sale_pm = money(outlet_summary["preco_medio_com_desc_projetado"])
    outlet_full_pm = money(outlet_summary["preco_cheio_medio_ponderado"])
    outlet_cost_pm = (
        sum(money(row.get("Custo Médio")) * money(row.get("Estoque Disponível")) for row in outlet_payload["rows"])
        / sum(money(row.get("Estoque Disponível")) for row in outlet_payload["rows"])
    )
    outlet_discount = 1 - outlet_sale_pm / outlet_full_pm if outlet_full_pm else 0
    outlet_units_needed = outlet_revenue / outlet_sale_pm if outlet_sale_pm else 0
    outlet_full_base = outlet_units_needed * outlet_full_pm
    outlet_cpv = outlet_units_needed * outlet_cost_pm

    scenarios = []
    for name, inverno_discount in [
        ("Inverno 2026 a preço cheio", 0.0),
        ("Inverno 2026 com 25% desconto", NEW_COLLECTION_DISCOUNT_SCENARIO),
    ]:
        inverno_sale_pm = full_pm * (1 - inverno_discount)
        inverno_units_needed = inverno_revenue / inverno_sale_pm if inverno_sale_pm else 0
        inverno_full_base = inverno_units_needed * full_pm
        inverno_cpv = inverno_units_needed * cost_pm
        total_full_base = outlet_full_base + inverno_full_base
        final_discount = 1 - TARGET_REVENUE / total_full_base if total_full_base else 0
        total_units = outlet_units_needed + inverno_units_needed
        total_cpv = outlet_cpv + inverno_cpv
        scenarios.append(
            {
                "Cenário": name,
                "Receita Total": TARGET_REVENUE,
                "Receita Outlet Promocional": outlet_revenue,
                "Receita Inverno 2026": inverno_revenue,
                "Desconto Outlet Médio": outlet_discount,
                "Desconto Inverno 2026": inverno_discount,
                "Desconto Médio Final": final_discount,
                "PM Outlet Venda": outlet_sale_pm,
                "PM Inverno Venda": inverno_sale_pm,
                "PM Total Venda": TARGET_REVENUE / total_units if total_units else 0,
                "Peças Outlet Estimadas": outlet_units_needed,
                "Peças Inverno Estimadas": inverno_units_needed,
                "Peças Totais Estimadas": total_units,
                "Cobertura Estoque Inverno": qty_total / inverno_units_needed if inverno_units_needed else 0,
                "CPV Outlet Estimado": outlet_cpv,
                "CPV Inverno Estimado": inverno_cpv,
                "CPV Total Estimado": total_cpv,
                "CPV % Receita": total_cpv / TARGET_REVENUE if TARGET_REVENUE else 0,
            }
        )

    summary = {
        "data_consulta": started_at,
        "colecao": TARGET_COLLECTION,
        "skus_ativos_estoque_positivo": len(detail_rows),
        "pecas_disponiveis": qty_total,
        "preco_medio_cheio_ponderado": full_pm,
        "preco_medio_api_atual_ponderado": api_pm,
        "custo_medio_ponderado": cost_pm,
        "valor_estoque_cheio": full_value_total,
        "valor_estoque_25_desc": discount25_value_total,
        "custo_estoque": cost_total,
        "pm_estimado_usuario": USER_ESTIMATED_INVERNO_PM,
        "diferenca_pm_vs_estimativa": full_pm - USER_ESTIMATED_INVERNO_PM,
        "diferenca_pm_vs_estimativa_pct": (full_pm / USER_ESTIMATED_INVERNO_PM - 1) if USER_ESTIMATED_INVERNO_PM else 0,
        "estimativa_pm_196_esta_correta": abs(full_pm - USER_ESTIMATED_INVERNO_PM) / USER_ESTIMATED_INVERNO_PM <= 0.05,
        "receita_inverno_assumida_10_pct": TARGET_REVENUE * INVERNO_REVENUE_SHARE,
        "observacao": "Preço cheio usa Preço Antigo quando maior que zero; senão Preço Venda. Quando a tabela local não tem preço, usa o preço atual retornado pelo endpoint frontend da API.",
    }

    save_json(OUT_DIR / "inverno_2026_scenarios_data.json", {"summary": summary, "scenarios": scenarios, "rows": detail_rows})
    logger.info("Inverno 2026: %s SKUs | %s peças | PM cheio %.2f | PM API %.2f", len(detail_rows), qty_total, full_pm, api_pm)
    logger.info("Cenários: %s", json.dumps(scenarios, ensure_ascii=False))


if __name__ == "__main__":
    main()
