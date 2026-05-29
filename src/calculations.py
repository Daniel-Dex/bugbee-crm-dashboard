from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class WeeklyMetrics:
    faturamento: float = 0
    faturamento_bruto: float = 0
    faturamento_liquido: float = 0
    devolucoes: float = 0
    pedidos: int = 0
    pedidos_site: int = 0
    pedidos_marketplace: int = 0
    receita_site: float = 0
    receita_marketplace: float = 0
    itens_vendidos: int = 0
    ticket_medio: float = 0
    pecas_por_pedido: float = 0
    desconto_medio: float | None = None
    venda_preco_cheio_total: float = 0
    valor_venda_total: float = 0
    clientes: int = 0
    clientes_novos: int | None = None
    clientes_recorrentes: int | None = None


def calculate_weekly_metrics(orders: list[dict], sales_items: list[dict], return_items: list[dict] | None = None) -> WeeklyMetrics:
    return_items = return_items or []
    order_ids = {row.get("pedido_codigo") or row.get("pedido_id") for row in orders if row.get("pedido_codigo") or row.get("pedido_id")}
    pedidos = len(order_ids)
    pedidos_site = len({row.get("pedido_codigo") or row.get("pedido_id") for row in orders if row.get("origem") == "Site"})
    pedidos_marketplace = len({row.get("pedido_codigo") or row.get("pedido_id") for row in orders if row.get("origem") == "Marketplace"})

    faturamento_bruto = sum(float(row.get("valor_total") or 0) for row in sales_items)
    devolucoes = abs(sum(float(row.get("valor_total") or 0) for row in return_items if row.get("is_devolucao")))
    faturamento_liquido = faturamento_bruto - devolucoes
    itens_vendidos = int(sum(float(row.get("quantidade") or 0) for row in sales_items))
    venda_preco_cheio_total = sum(float(row.get("valor_preco_cheio_total") or 0) for row in sales_items)
    valor_venda_total = sum(float(row.get("valor_total") or 0) for row in sales_items)
    clientes = len({row.get("cliente") for row in orders if row.get("cliente")})

    receita_por_origem = defaultdict(float)
    order_origin = {}
    for row in orders:
        if row.get("pedido_id"):
            order_origin[str(row.get("pedido_id"))] = row.get("origem")
        if row.get("pedido_codigo"):
            order_origin[str(row.get("pedido_codigo"))] = row.get("origem")
    for item in sales_items:
        origem = item.get("origem") or order_origin.get(str(item.get("pedido_id"))) or order_origin.get(str(item.get("pedido_codigo")))
        receita_por_origem[origem] += float(item.get("valor_total") or 0)

    desconto_medio = None
    if venda_preco_cheio_total > 0:
        desconto_medio = 1 - (valor_venda_total / venda_preco_cheio_total)

    return WeeklyMetrics(
        faturamento=faturamento_liquido,
        faturamento_bruto=faturamento_bruto,
        faturamento_liquido=faturamento_liquido,
        devolucoes=devolucoes,
        pedidos=pedidos,
        pedidos_site=pedidos_site,
        pedidos_marketplace=pedidos_marketplace,
        receita_site=receita_por_origem["Site"],
        receita_marketplace=receita_por_origem["Marketplace"],
        itens_vendidos=itens_vendidos,
        ticket_medio=faturamento_liquido / pedidos if pedidos else 0,
        pecas_por_pedido=itens_vendidos / pedidos if pedidos else 0,
        desconto_medio=desconto_medio,
        venda_preco_cheio_total=venda_preco_cheio_total,
        valor_venda_total=valor_venda_total,
        clientes=clientes,
    )


def compare(current: float, previous: float) -> dict[str, float | None]:
    if previous == 0:
        return {"abs": current - previous, "pct": None}
    return {"abs": current - previous, "pct": current / previous - 1}


def rank_by(items: list[dict], key: str, label_key: str, limit: int = 20) -> list[dict]:
    agg: dict[str, float] = defaultdict(float)
    qty: dict[str, float] = defaultdict(float)
    for item in items:
        label = item.get(label_key) or "Não informado"
        agg[label] += float(item.get(key) or 0)
        qty[label] += float(item.get("quantidade") or 0)
    rows = [{"nome": name, "valor": value, "quantidade": qty[name]} for name, value in agg.items()]
    return sorted(rows, key=lambda x: x["valor"], reverse=True)[:limit]


def low_stock(stock: list[dict], limit: int = 50) -> list[dict]:
    rows = [
        row for row in stock
        if float(row.get("quantidade_disponivel") or 0) <= max(float(row.get("quantidade_minima") or 0), 1)
    ]
    return sorted(rows, key=lambda x: float(x.get("quantidade_disponivel") or 0))[:limit]
