from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import Period, Settings
from .magazord_client import EndpointResult, MagazordClient


def save_json(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def extract_magazord(settings: Settings, period: Period, logger) -> dict[str, list[dict]]:
    client = MagazordClient(settings.base_url, settings.api_key, settings.api_secret, logger)
    raw_run_dir = settings.raw_dir / period.current_end.isoformat()
    results: dict[str, EndpointResult] = {}

    calls = [
        ("pedidos", lambda: client.buscar_pedidos_completos(period.current_start, period.current_end)),
        ("pedidos_semana_anterior", lambda: client.buscar_pedidos_completos(period.previous_start, period.previous_end)),
        ("pedidos_ano_anterior", lambda: client.buscar_pedidos_completos(period.yoy_start, period.yoy_end)),
        ("notas_fiscais", lambda: client.buscar_notas_fiscais_com_itens(period.current_start, period.current_end)),
        ("notas_fiscais_semana_anterior", lambda: client.buscar_notas_fiscais_com_itens(period.previous_start, period.previous_end)),
        ("notas_fiscais_ano_anterior", lambda: client.buscar_notas_fiscais_com_itens(period.yoy_start, period.yoy_end)),
        ("notas_fiscais_entrada", lambda: client.buscar_notas_fiscais_com_itens(period.current_start, period.current_end, tipo=0)),
        ("notas_fiscais_entrada_semana_anterior", lambda: client.buscar_notas_fiscais_com_itens(period.previous_start, period.previous_end, tipo=0)),
        ("notas_fiscais_entrada_ano_anterior", lambda: client.buscar_notas_fiscais_com_itens(period.yoy_start, period.yoy_end, tipo=0)),
        ("clientes", lambda: client.buscar_clientes(period.current_start, period.current_end)),
        ("produtos", client.buscar_produtos),
        ("produtos_completos", client.buscar_produtos_completos),
        ("tabelas_preco", client.buscar_tabelas_preco),
        ("itens_tabela_preco", client.buscar_itens_tabela_preco),
        ("caracteristicas", client.buscar_caracteristicas),
        ("estoque", client.buscar_estoque),
        ("categorias", client.buscar_categorias),
        ("formas_pagamento", client.buscar_formas_pagamento),
        ("canais_venda", client.buscar_canais_venda),
    ]

    for name, fn in calls:
        try:
            result = fn()
            results[name] = result
            save_json(raw_run_dir / f"{name}.json", result.rows)
        except Exception as exc:
            logger.warning("Falha ao consultar %s: %s", name, exc)
            results[name] = EndpointResult(name, "", [], warning=str(exc))
            save_json(raw_run_dir / f"{name}.json", [])

    save_json(raw_run_dir / "_periodo.json", [asdict(period)])
    return {name: result.rows for name, result in results.items()}


def extract_product_characteristics(settings: Settings, period: Period, skus: list[str], logger) -> list[dict]:
    client = MagazordClient(settings.base_url, settings.api_key, settings.api_secret, logger)
    raw_run_dir = settings.raw_dir / period.current_end.isoformat()
    rows: list[dict] = []
    for sku in sorted({str(sku) for sku in skus if sku}):
        try:
            result = client.buscar_produto_caracteristicas(sku)
            rows.append({"sku": sku, "caracteristicas": result.rows})
        except Exception as exc:
            logger.warning("Falha ao consultar características do produto %s: %s", sku, exc)
    save_json(raw_run_dir / "produto_caracteristicas_relevantes.json", rows)
    logger.info("produto_caracteristicas_relevantes: %s produtos", len(rows))
    return rows
