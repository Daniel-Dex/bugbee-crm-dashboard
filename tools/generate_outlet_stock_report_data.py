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
DEFAULT_DISCOUNT = 0.55
COLLECTION_DISCOUNTS = {"Verão 2026": 0.35}
COVERAGE_RATIO = 1.5


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


def is_outlet_yes(chars: list[dict[str, Any]]) -> bool:
    value, desc = characteristic_value(chars, 9)
    if isinstance(value, bool):
        return value
    text = str(desc if desc is not None else value).strip().lower()
    return text in {"sim", "true", "1", "yes"}


def projected_discount(collection: Any) -> float:
    return COLLECTION_DISCOUNTS.get(str(collection or "").strip(), DEFAULT_DISCOUNT)


def get_chars_for_sku(args: tuple[str, str, str]) -> dict[str, Any]:
    sku, base_url, api_key = args
    logger = logging.getLogger(f"chars.{sku}")
    client = MagazordClient(base_url, api_key, os.environ["MAGAZORD_API_SECRET"], logger, timeout=45)
    try:
        result = client.buscar_produto_caracteristicas(sku)
        return {"sku": sku, "caracteristicas": result.rows, "erro": None}
    except Exception as exc:
        return {"sku": sku, "caracteristicas": [], "erro": str(exc)}


def main() -> None:
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("outlet_stock")
    client = make_client(logger)

    started_at = datetime.now().isoformat(timespec="seconds")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Consultando estoque, produtos e características gerais")
    stock_rows = client.buscar_estoque().rows
    products = client.buscar_produtos().rows
    characteristics = client.buscar_caracteristicas().rows
    save_json(RAW_DIR / "outlet_estoque_api.json", stock_rows)
    save_json(RAW_DIR / "outlet_produtos_api.json", products)
    save_json(RAW_DIR / "outlet_caracteristicas_api.json", characteristics)

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
    logger.info("SKUs ativos com estoque positivo para consulta de características: %s", len(candidate_skus))

    char_cache_path = RAW_DIR / "outlet_produto_caracteristicas_api.json"
    if char_cache_path.exists():
        char_rows = json.loads(char_cache_path.read_text(encoding="utf-8"))
    else:
        base_url = os.environ["MAGAZORD_BASE_URL"]
        api_key = os.environ["MAGAZORD_API_KEY"]
        char_rows = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(get_chars_for_sku, (sku, base_url, api_key)) for sku in candidate_skus]
            for index, future in enumerate(as_completed(futures), start=1):
                char_rows.append(future.result())
                if index % 250 == 0:
                    logger.info("Características consultadas: %s/%s", index, len(candidate_skus))
                    save_json(char_cache_path, char_rows)
                time.sleep(0.005)
        save_json(char_cache_path, char_rows)

    char_by_sku = {str(row["sku"]): row for row in char_rows}
    price_lookup = load_reference_lookup()

    report_rows: list[dict[str, Any]] = []
    missing_price = 0
    for sku in candidate_skus:
        chars = char_by_sku.get(sku, {}).get("caracteristicas", []) or []
        if not is_outlet_yes(chars):
            continue

        stock = stock_by_sku[sku]
        product = active_derivations[sku]
        collection_value, collection = characteristic_value(chars, 5)
        line_value, product_line = characteristic_value(chars, 7)
        outlet_value, outlet = characteristic_value(chars, 9)

        price_info = price_lookup.get(sku) or {}
        sale_price = money(price_info.get("preco_tabela_venda"))
        old_price = money(price_info.get("preco_antigo"))
        full_price = old_price if old_price > 0 else sale_price
        if full_price <= 0:
            full_price = money(price_info.get("preco_cheio"))
        if sale_price <= 0:
            sale_price = full_price
        if full_price <= 0:
            missing_price += 1

        qty = money(stock["quantidade_disponivel"])
        avg_cost = stock["custo_medio_total"] / stock["custo_medio_peso"] if stock["custo_medio_peso"] else 0
        discount = projected_discount(collection)
        discounted_price = full_price * (1 - discount)
        report_rows.append(
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
                "Outlet ID": outlet_value,
                "Outlet": outlet,
                "Estoque Disponível": qty,
                "Estoque Físico": money(stock["quantidade_fisica"]),
                "Reservado": money(stock["quantidade_reservada"]),
                "Depósitos": ", ".join(sorted(d for d in stock["depositos"] if d)),
                "Custo Médio": avg_cost,
                "Preço Antigo": old_price,
                "Preço Venda": sale_price,
                "Preço Cheio Regra": full_price,
                "Desconto Projetado": discount,
                "Preço c/ Desc. Projetado": discounted_price,
                "Valor Potencial c/ Desc.": qty * discounted_price,
                "Valor Cheio Estoque": qty * full_price,
                "Peças Necessárias no PM Atual": None,
                "Fonte Preço": "Tabela de preço local" if price_info else "Não encontrado",
                "Última Atualização Estoque": stock.get("ultima_atualizacao"),
            }
        )

    report_rows.sort(key=lambda row: (money(row["Valor Potencial c/ Desc."]), money(row["Estoque Disponível"])), reverse=True)
    total_qty = sum(money(row["Estoque Disponível"]) for row in report_rows)
    total_potential = sum(money(row["Valor Potencial c/ Desc."]) for row in report_rows)
    weighted_full_price = sum(money(row["Preço Cheio Regra"]) * money(row["Estoque Disponível"]) for row in report_rows) / total_qty if total_qty else 0
    weighted_discounted_price = total_potential / total_qty if total_qty else 0
    required_pieces = TARGET_REVENUE / weighted_discounted_price if weighted_discounted_price else 0
    required_stock_with_coverage = required_pieces * COVERAGE_RATIO
    additional_pieces = max(0, required_stock_with_coverage - total_qty)
    coverage = total_potential / TARGET_REVENUE if TARGET_REVENUE else 0
    stock_coverage_ratio = total_qty / required_pieces if required_pieces else 0

    summary = {
        "data_consulta": started_at,
        "skus_candidatos_ativos_estoque_positivo": len(candidate_skus),
        "skus_outlet_sim": len(report_rows),
        "pecas_outlet_disponiveis": total_qty,
        "preco_cheio_medio_ponderado": weighted_full_price,
        "preco_medio_com_desc_projetado": weighted_discounted_price,
        "valor_potencial_com_desc_projetado": total_potential,
        "meta_receita_junho_julho": TARGET_REVENUE,
        "cobertura_meta": coverage,
        "cobertura_estoque_objetivo": COVERAGE_RATIO,
        "pecas_necessarias_para_vender_meta": required_pieces,
        "pecas_necessarias_com_cobertura": required_stock_with_coverage,
        "cobertura_estoque_atual": stock_coverage_ratio,
        "pecas_outlet_adicionais_necessarias": additional_pieces,
        "skus_sem_preco": missing_price,
        "observacao_preco_api": "Endpoint /v2/site/tabelaPrecoItem retornou 403; preço usado vem das tabelas locais já exportadas do Magazord, com regra Preço Antigo=0 -> Preço Venda.",
        "observacao_desconto": "Verão 2026 recalculado com 35% de desconto médio; demais coleções mantidas em 55%. Necessidade de peças considera cobertura promocional de 1,5:1.",
    }

    save_json(OUT_DIR / "outlet_stock_report_data.json", {"summary": summary, "rows": report_rows})
    logger.info("Relatório base salvo com %s SKUs outlet", len(report_rows))
    logger.info("Potencial: %.2f | Meta: %.2f | Cobertura: %.1f%%", total_potential, TARGET_REVENUE, coverage * 100)


if __name__ == "__main__":
    main()
