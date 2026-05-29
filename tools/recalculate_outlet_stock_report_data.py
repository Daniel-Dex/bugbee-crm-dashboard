from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "outputs" / "outlet_stock" / "outlet_stock_report_data.json"
TARGET_REVENUE = 1_367_000.0
DEFAULT_DISCOUNT = 0.55
COLLECTION_DISCOUNTS = {"Verão 2026": 0.35}
COVERAGE_RATIO = 1.5


def money(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def projected_discount(collection: Any) -> float:
    return COLLECTION_DISCOUNTS.get(str(collection or "").strip(), DEFAULT_DISCOUNT)


payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
rows = payload["rows"]

for row in rows:
    discount = projected_discount(row.get("Coleção"))
    full_price = money(row.get("Preço Cheio Regra"))
    qty = money(row.get("Estoque Disponível"))
    discounted_price = full_price * (1 - discount)
    row["Desconto Projetado"] = discount
    row["Preço c/ Desc. Projetado"] = discounted_price
    row["Valor Potencial c/ Desc."] = qty * discounted_price
    row.pop("Preço c/ 55% desc.", None)
    row.pop("Valor Potencial c/ 55%", None)

rows.sort(key=lambda row: (money(row["Valor Potencial c/ Desc."]), money(row["Estoque Disponível"])), reverse=True)

total_qty = sum(money(row["Estoque Disponível"]) for row in rows)
total_potential = sum(money(row["Valor Potencial c/ Desc."]) for row in rows)
weighted_full_price = (
    sum(money(row["Preço Cheio Regra"]) * money(row["Estoque Disponível"]) for row in rows) / total_qty
    if total_qty
    else 0
)
weighted_discounted_price = total_potential / total_qty if total_qty else 0
required_pieces_to_sell = TARGET_REVENUE / weighted_discounted_price if weighted_discounted_price else 0
required_stock_with_coverage = required_pieces_to_sell * COVERAGE_RATIO
additional_pieces = max(0, required_stock_with_coverage - total_qty)
revenue_coverage = total_potential / TARGET_REVENUE if TARGET_REVENUE else 0
stock_coverage = total_qty / required_pieces_to_sell if required_pieces_to_sell else 0

summary = payload["summary"]
summary.update(
    {
        "data_recalculo": datetime.now().isoformat(timespec="seconds"),
        "pecas_outlet_disponiveis": total_qty,
        "preco_cheio_medio_ponderado": weighted_full_price,
        "preco_medio_com_desc_projetado": weighted_discounted_price,
        "valor_potencial_com_desc_projetado": total_potential,
        "meta_receita_junho_julho": TARGET_REVENUE,
        "cobertura_meta": revenue_coverage,
        "cobertura_estoque_objetivo": COVERAGE_RATIO,
        "pecas_necessarias_para_vender_meta": required_pieces_to_sell,
        "pecas_necessarias_com_cobertura": required_stock_with_coverage,
        "cobertura_estoque_atual": stock_coverage,
        "pecas_outlet_adicionais_necessarias": additional_pieces,
        "observacao_desconto": "Verão 2026 recalculado com 35% de desconto médio; demais coleções mantidas em 55%. Necessidade de peças considera cobertura promocional de 1,5:1.",
    }
)
summary.pop("preco_medio_com_55_desc", None)
summary.pop("valor_potencial_com_55_desc", None)
summary.pop("pecas_necessarias_no_pm_atual", None)

DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
