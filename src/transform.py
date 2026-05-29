from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


ORIGEM_MAP = {1: "Site", 2: "Marketplace", 3: "Manual", 4: "PDV"}
SITUACAO_TIPO_MAP = {1: "Normal", 2: "Anomalia", 3: "Cancelado", 4: "Aguardando Terceiro"}
DEVOLUCAO_CFOP_PREFIXES = ("120", "141", "220", "241", "320", "520", "541", "620", "641")


def pick(row: dict[str, Any], *names: str, default=None):
    for name in names:
        if not isinstance(row, dict) or name not in row:
            continue
        value = row[name]
        if isinstance(value, str) and value.startswith("#"):
            continue
        if value not in (None, ""):
            return row[name]
    return default


def money(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        return float(text.replace(".", "").replace(",", ".") if "," in text else text)
    except Exception:
        return 0.0


def as_int(value) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def parent_sku(sku: Any) -> str | None:
    if sku in (None, ""):
        return None
    text = str(sku).strip()
    return text.split("-", 1)[0] if "-" in text else text


def split_product_variant(description: Any) -> tuple[str | None, str | None, str | None]:
    if not description:
        return None, None, None
    parts = [part.strip() for part in str(description).split(" - ") if part.strip()]
    if len(parts) >= 3:
        return " - ".join(parts[:-2]), parts[-2], parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return str(description).strip(), None, None


def first_cfop(xml: Any) -> str | None:
    if not xml:
        return None
    match = re.search(r"<CFOP>(\d+)</CFOP>", str(xml))
    return match.group(1) if match else None


def is_devolucao_nota(invoice: dict[str, Any]) -> bool:
    tipo = as_int(pick(invoice, "tipo"))
    cfop = first_cfop(pick(invoice, "xml"))
    return tipo == 0 and bool(cfop and cfop.startswith(DEVOLUCAO_CFOP_PREFIXES))


def flatten_items_from_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        order_id = pick(order, "id", "codigo", "codigoPedido", "pedido")
        origem_codigo = as_int(pick(order, "origem"))
        origem = ORIGEM_MAP.get(origem_codigo, "Não informado")
        rastreios = pick(order, "arrayPedidoRastreio", default=[]) or []
        if not isinstance(rastreios, list):
            rastreios = []
        direct_items = pick(order, "itens", "items", "itensPedido", default=[]) or []
        item_groups = [r.get("pedidoItem", []) for r in rastreios if isinstance(r, dict)]
        if isinstance(direct_items, list) and direct_items:
            item_groups.append(direct_items)
        for items in item_groups:
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                sku = pick(item, "produtoDerivacaoCodigo", "produto", "codigoProduto", "sku", "derivacaoCodigo")
                desc = pick(item, "produtoNome", "produtoTitulo", "nome", "nomeProduto", "descricao")
                produto_base, cor, tamanho = split_product_variant(desc)
                rows.append({
                    "pedido_id": order_id,
                    "pedido_codigo": pick(order, "codigo", "codigoPedido", "pedido"),
                    "data": pick(order, "dataHora", "data", "dataEmissao"),
                    "cliente": pick(order, "pessoaNome", "cliente", "nomeCliente"),
                    "sku": sku,
                    "sku_pai": pick(item, "codigoPai", default=parent_sku(sku)),
                    "produto": produto_base or desc,
                    "descricao_completa": desc,
                    "cor": cor or pick(item, "cor"),
                    "tamanho": tamanho or pick(item, "tamanho", "produtoDerivacaoNome"),
                    "categoria": pick(item, "categoria", "categoriaNome"),
                    "categoria_id": pick(item, "categoria_id"),
                    "quantidade": money(pick(item, "quantidade", "quantidadeItem", default=1)),
                    "valor_unitario": money(pick(item, "valorUnitario", "precoVenda")),
                    "valor_total": money(pick(item, "valorItem", "valorTotal", "precoVenda", "valor", "total")),
                    "valor_desconto": money(pick(item, "valorDesconto")),
                    "preco_cheio": money(pick(item, "precoAntigo", "valorDe", "precoDe")),
                    "origem_codigo": origem_codigo,
                    "origem": origem,
                    "marketplace_id": pick(order, "marketplaceId", "lojaDoMarketplaceId"),
                    "marketplace_nome": pick(order, "marketplaceNome", "lojaDoMarketplaceNome"),
                    "situacao_codigo": pick(order, "pedidoSituacao", "situacao"),
                    "situacao": pick(order, "pedidoSituacaoDescricao", "situacaoDescricao"),
                    "situacao_tipo": SITUACAO_TIPO_MAP.get(as_int(pick(order, "pedidoSituacaoTipo"))),
                })
    return rows


def flatten_items_from_invoices(invoices: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for invoice in invoices:
        invoice_id = pick(invoice, "id")
        order_id = pick(invoice, "pedidoId", "pedidoCodigo")
        tipo_nota = as_int(pick(invoice, "tipo"))
        cfop = first_cfop(pick(invoice, "xml"))
        devolucao = is_devolucao_nota(invoice)
        items = pick(invoice, "itens", default=[]) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            desc = pick(item, "descricao")
            produto_base, cor, tamanho = split_product_variant(desc)
            rows.append({
                "nota_fiscal_id": invoice_id,
                "pedido_id": order_id,
                "data": pick(invoice, "dataEmissao"),
                "numero_nf": pick(invoice, "numero"),
                "tipo_nota": tipo_nota,
                "tipo_nota_descricao": "Entrada" if tipo_nota == 0 else "Saída" if tipo_nota == 1 else None,
                "cfop": cfop,
                "is_devolucao": devolucao,
                "sku": pick(item, "codigo"),
                "sku_pai": parent_sku(pick(item, "codigo")),
                "produto": produto_base or desc,
                "descricao_completa": desc,
                "cor": cor,
                "tamanho": tamanho,
                "categoria": None,
                "quantidade": money(pick(item, "quantidade", default=1)),
                "valor_unitario": money(pick(item, "valorUnitario")),
                "valor_produto": money(pick(item, "valorProduto")),
                "valor_desconto": money(pick(item, "valorDesconto")),
                "valor_frete": money(pick(item, "valorFrete")),
                "valor_total": money(pick(item, "valorTotal", "valorProduto")),
                "ncm": pick(item, "ncm"),
                "ean": pick(item, "ean"),
            })
    return rows


def normalize_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for order in orders:
        origem_codigo = as_int(pick(order, "origem"))
        normalized.append({
            "pedido_id": pick(order, "id", "codigo", "codigoPedido", "pedido"),
            "pedido_codigo": pick(order, "codigo", "codigoPedido", "pedido"),
            "data": pick(order, "dataHora", "data", "dataEmissao"),
            "cliente": pick(order, "pessoaNome", "cliente", "nomeCliente"),
            "valor_produto": money(pick(order, "valorProduto")),
            "valor_frete": money(pick(order, "valorFrete", "frete")),
            "valor_desconto": money(pick(order, "valorDesconto", "desconto")),
            "valor_total": money(pick(order, "valorTotalFinal", "valorTotal", "total", "valor", "valorPedido")),
            "origem_codigo": origem_codigo,
            "origem": ORIGEM_MAP.get(origem_codigo, "Não informado"),
            "marketplace_id": pick(order, "marketplaceId", "lojaDoMarketplaceId"),
            "marketplace_nome": pick(order, "marketplaceNome", "lojaDoMarketplaceNome"),
            "situacao_codigo": pick(order, "pedidoSituacao", "situacao"),
            "situacao": pick(order, "pedidoSituacaoDescricao", "situacaoDescricao"),
            "situacao_tipo": SITUACAO_TIPO_MAP.get(as_int(pick(order, "pedidoSituacaoTipo"))),
        })
    return normalized


def normalize_stock(stock: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sku": pick(row, "produto"),
            "sku_pai": parent_sku(pick(row, "produto")),
            "produto": pick(row, "descricaoProduto"),
            "deposito": pick(row, "deposito"),
            "quantidade_fisica": money(pick(row, "quantidadeFisica")),
            "quantidade_disponivel": money(pick(row, "quantidadeDisponivelVenda")),
            "quantidade_minima": money(pick(row, "quantidadeMinimaEstoque")),
            "custo_medio": money(pick(row, "custoMedio")),
            "ativo": pick(row, "ativo"),
        }
        for row in stock
    ]


def build_category_lookup(categories: Iterable[dict[str, Any]]) -> dict[Any, str]:
    return {pick(row, "id", "codigo"): pick(row, "nome", "descricao") for row in categories if pick(row, "id", "codigo")}


def build_category_details(categories: Iterable[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    details = {}
    for row in categories:
        category_id = pick(row, "id", "codigo")
        if category_id:
            details[category_id] = {
                "id": category_id,
                "nome": pick(row, "nome", "descricao"),
                "pai": pick(row, "pai"),
            }
    return details


def top_category_name(category_id: Any, details: dict[Any, dict[str, Any]]) -> str | None:
    current = category_id
    visited = set()
    last_name = None
    while current and current not in visited:
        visited.add(current)
        info = details.get(current) or {}
        last_name = info.get("nome") or last_name
        current = info.get("pai")
    return last_name


def build_product_lookup(products: Iterable[dict[str, Any]], category_lookup: dict[Any, str]) -> dict[str, dict[str, Any]]:
    category_details = build_category_details([{"id": key, "nome": value, "pai": None} for key, value in category_lookup.items()])
    return build_product_lookup_with_categories(products, category_lookup, category_details)


def build_product_lookup_with_categories(products: Iterable[dict[str, Any]], category_lookup: dict[Any, str], category_details: dict[Any, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for product in products:
        parent = pick(product, "codigo")
        categories = pick(product, "categorias", default=[]) or []
        category_id = categories[0] if isinstance(categories, list) and categories else None
        category_name = category_lookup.get(category_id)
        genero = top_category_name(category_id, category_details)
        base = {
            "sku_pai": parent,
            "produto": pick(product, "nome"),
            "categoria_id": category_id,
            "categoria": category_name,
            "genero": genero,
            "ativo": pick(product, "ativo"),
        }
        if parent:
            lookup[str(parent)] = dict(base, sku=parent)
        derivations = pick(product, "derivacoes", default=[]) or []
        if isinstance(derivations, list):
            for der in derivations:
                if not isinstance(der, dict):
                    continue
                sku = pick(der, "codigo")
                if sku:
                    _, cor, tamanho = split_product_variant(pick(der, "nome"))
                    lookup[str(sku)] = dict(base, sku=sku, cor=cor, tamanho=tamanho, derivacao=pick(der, "nome"))
    return lookup


def build_price_lookup(price_items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in price_items:
        sku = pick(row, "produto_derivacao_codigo_pai", "produtoDerivacaoCodigo", "codigo", "sku")
        if not sku:
            continue
        old_price = money(pick(row, "preco_antigo", "precoAntigo"))
        sale_price = money(pick(row, "preco_venda", "precoVenda"))
        full_price = old_price if old_price > 0 else sale_price
        if full_price or sale_price:
            lookup[str(sku)] = {
                "preco_cheio": full_price,
                "preco_tabela_venda": sale_price,
                "tabela_preco": pick(pick(row, "tabela_preco", default={}) or {}, "nome"),
            }
    return lookup


def build_characteristic_lookup(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        sku = pick(row, "sku", "codigo_produto", "codigoProduto")
        if not sku:
            continue
        info = lookup.setdefault(str(sku), {})
        chars = pick(row, "caracteristicas", default=[]) or []
        if not isinstance(chars, list):
            continue
        for char in chars:
            if not isinstance(char, dict):
                continue
            code = as_int(pick(char, "codigo"))
            value = pick(char, "valorDescritivo", "valorDescricao", "valor")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            if code == 5:
                info["colecao"] = value
            elif code == 7:
                info["linha_produto"] = value
    return lookup


def enrich_items(items: list[dict[str, Any]], *lookups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for item in items:
        row = dict(item)
        sku = str(row.get("sku") or "")
        sku_pai = str(row.get("sku_pai") or parent_sku(sku) or "")
        for lookup in lookups:
            info = lookup.get(sku) or lookup.get(sku_pai) or {}
            for key, value in info.items():
                if key == "sku_pai" and value not in (None, ""):
                    row[key] = value
                elif row.get(key) in (None, "", 0):
                    row[key] = value
            sku_pai = str(row.get("sku_pai") or parent_sku(sku) or "")
        if not row.get("preco_cheio"):
            row["preco_cheio"] = row.get("valor_unitario") or 0
        row["valor_preco_cheio_total"] = money(row.get("preco_cheio")) * money(row.get("quantidade") or 0)
        enriched.append(row)
    return enriched
