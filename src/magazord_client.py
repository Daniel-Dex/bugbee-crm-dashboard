from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:  # Dependency is installed via requirements.txt in production.
    requests = None
    HTTPBasicAuth = None


@dataclass(frozen=True)
class EndpointResult:
    name: str
    endpoint: str
    rows: list[dict[str, Any]]
    warning: str | None = None


class MagazordClient:
    """Small wrapper around documented MagaZord REST endpoints.

    The official docs identify BasicAuth, `page/limit` pagination for most v2
    endpoints, `offset/limit` pagination for `/api/v1/listEstoque`, and JSON
    payload filters for `/api/v3/produtos/query`.
    """

    def __init__(self, base_url: str, api_key: str, api_secret: str, logger: logging.Logger, timeout: int = 45):
        if requests is None or HTTPBasicAuth is None:
            raise RuntimeError("Dependência ausente: requests. Execute `pip install -r requirements.txt`.")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(api_key, api_secret)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.timeout = timeout
        self.logger = logger

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        if self.base_url.endswith("/api"):
            if path.startswith("/api/"):
                return f"{self.base_url[:-4]}{path}"
            return f"{self.base_url}{path}"
        if path.startswith("/api/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/api{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        url = self._url(path)
        safe_params = kwargs.get("params") or {}
        self.logger.info("Consultando endpoint %s params=%s", path, safe_params)
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "10"))
            self.logger.warning("Rate limit em %s; aguardando %ss", path, retry_after)
            time.sleep(retry_after)
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _items(payload: dict[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], bool]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)], False
        data = payload.get("data", payload)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)], False
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)], bool(data.get("has_more"))
            if all(k in data for k in ("page", "total_pages")):
                return [], int(data.get("page") or 1) < int(data.get("total_pages") or 1)
        return [], False

    def get_paginated(self, name: str, path: str, params: dict[str, Any] | None = None, limit: int = 100) -> EndpointResult:
        rows: list[dict[str, Any]] = []
        page = 1
        params = dict(params or {})
        while True:
            params.update({"limit": limit, "page": page})
            payload = self._request("GET", path, params=params)
            items, has_more = self._items(payload)
            rows.extend(items)
            if not has_more and len(items) < limit:
                break
            page += 1
        self.logger.info("%s: %s registros", name, len(rows))
        return EndpointResult(name, path, rows)

    def get_offset_paginated(self, name: str, path: str, params: dict[str, Any] | None = None, limit: int = 100) -> EndpointResult:
        rows: list[dict[str, Any]] = []
        offset = 0
        params = dict(params or {})
        while True:
            params.update({"limit": limit, "offset": offset})
            payload = self._request("GET", path, params=params)
            items, _ = self._items(payload)
            rows.extend(items)
            if len(items) < limit:
                break
            offset += limit
        self.logger.info("%s: %s registros", name, len(rows))
        return EndpointResult(name, path, rows)

    def post_query_paginated(self, name: str, path: str, payload: dict[str, Any] | None = None, limit: int = 100) -> EndpointResult:
        rows: list[dict[str, Any]] = []
        page = 1
        payload = dict(payload or {})
        while True:
            body = dict(payload)
            body.update({"limit": limit, "page": page})
            data = self._request("POST", path, json=body)
            items, has_more = self._items(data)
            rows.extend(items)
            if not has_more and len(items) < limit:
                break
            page += 1
        self.logger.info("%s: %s registros", name, len(rows))
        return EndpointResult(name, path, rows)

    def buscar_pedidos(self, start: date, end: date) -> EndpointResult:
        return self.get_paginated(
            "pedidos",
            "/v2/site/pedido",
            {
                "dataHora[gte]": start.isoformat(),
                "dataHora[lte]": end.isoformat(),
                "orderDirection": "asc",
            },
        )

    def buscar_pedido_detalhe(self, codigo_pedido: int | str) -> dict[str, Any]:
        payload = self._request("GET", f"/v2/site/pedido/{codigo_pedido}")
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return data if isinstance(data, dict) else {}

    def buscar_pedidos_completos(self, start: date, end: date) -> EndpointResult:
        pedidos = self.buscar_pedidos(start, end).rows
        rows: list[dict[str, Any]] = []
        for pedido in pedidos:
            codigo = pedido.get("codigo") or pedido.get("id")
            if not codigo:
                continue
            try:
                detalhe = self.buscar_pedido_detalhe(codigo)
                rows.append(detalhe or pedido)
            except Exception as exc:
                self.logger.warning("Falha ao consultar detalhe do pedido %s: %s", codigo, exc)
                rows.append(pedido)
        self.logger.info("pedidos_completos: %s registros", len(rows))
        return EndpointResult("pedidos_completos", "/v2/site/pedido/{codigoPedido}", rows)

    def buscar_notas_fiscais(self, start: date, end: date, tipo: int = 1) -> EndpointResult:
        return self.get_paginated(
            "notas_fiscais",
            "/v2/faturamento/notaFiscal",
            {"date": start.isoformat(), "date_end": end.isoformat(), "tipo": tipo, "orderDirection": "asc"},
            limit=100,
        )

    def buscar_nota_fiscal_detalhe(self, nota_fiscal_id: int | str) -> dict[str, Any]:
        payload = self._request("GET", f"/v2/faturamento/notaFiscal/{nota_fiscal_id}")
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(data, dict) and "items" in data and isinstance(data["items"], list) and data["items"]:
            return data["items"][0]
        return data if isinstance(data, dict) else {}

    def buscar_notas_fiscais_com_itens(self, start: date, end: date, tipo: int = 1) -> EndpointResult:
        notas = self.buscar_notas_fiscais(start, end, tipo=tipo).rows
        rows: list[dict[str, Any]] = []
        for nota in notas:
            nota_id = nota.get("id")
            if not nota_id:
                continue
            try:
                detalhe = self.buscar_nota_fiscal_detalhe(nota_id)
                if detalhe:
                    rows.append(detalhe)
            except Exception as exc:
                self.logger.warning("Falha ao consultar detalhe da nota fiscal %s: %s", nota_id, exc)
        self.logger.info("notas_fiscais_com_itens: %s registros", len(rows))
        return EndpointResult("notas_fiscais_com_itens", "/v2/faturamento/notaFiscal/{id}", rows)

    def buscar_pagamentos_pedido(self, pedido_id: int | str) -> EndpointResult:
        return self.get_paginated("pagamentos_pedido", f"/v2/site/pedido/{pedido_id}/payments")

    def buscar_clientes(self, start: date, end: date) -> EndpointResult:
        return self.get_paginated(
            "clientes",
            "/v2/site/pessoa",
            {"dataCadastro[gte]": start.isoformat(), "dataCadastro[lte]": end.isoformat(), "orderDirection": "asc"},
        )

    def buscar_produtos(self) -> EndpointResult:
        return self.get_paginated("produtos", "/v2/site/produto", {"orderDirection": "asc"})

    def buscar_produtos_completos(self) -> EndpointResult:
        return self.post_query_paginated("produtos_completos", "/v3/produtos/query", {"filters": []}, limit=50)

    def buscar_tabelas_preco(self) -> EndpointResult:
        return self.get_paginated("tabelas_preco", "/v2/site/tabelaPreco", {"situacao": "ativa", "orderDirection": "asc"})

    def buscar_itens_tabela_preco(self) -> EndpointResult:
        return self.get_paginated("itens_tabela_preco", "/v2/site/tabelaPrecoItem", {"orderDirection": "asc"})

    def buscar_caracteristicas(self) -> EndpointResult:
        return self.get_paginated("caracteristicas", "/v2/site/caracteristica", {"ativo": "true", "orderDirection": "asc"})

    def buscar_produto_caracteristicas(self, codigo_produto: str) -> EndpointResult:
        payload = self._request("GET", f"/v2/site/produto/{codigo_produto}/caracteristica")
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        rows = data if isinstance(data, list) else []
        return EndpointResult("produto_caracteristicas", f"/v2/site/produto/{codigo_produto}/caracteristica", rows)

    def buscar_estoque(self) -> EndpointResult:
        return self.get_offset_paginated("estoque", "/v1/listEstoque", {"ativo": "true"}, limit=100)

    def buscar_categorias(self) -> EndpointResult:
        return self.get_paginated("categorias", "/v2/site/categoria", {"orderDirection": "asc"})

    def buscar_formas_pagamento(self) -> EndpointResult:
        return self.get_paginated("formas_pagamento", "/v2/site/forma-recebimento", {"orderDirection": "asc"})

    def buscar_canais_venda(self) -> EndpointResult:
        return self.get_paginated("canais_venda", "/v2/site/estoque/projecaoEstoque/canaisVenda")
