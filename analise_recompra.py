from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from src.config import load_settings
from src.magazord_client import MagazordClient


VALID_STATUS_CODES = {4, 5, 6, 7, 8, 12, 23, 30}
INVALID_STATUS_CODES = {1, 2, 3, 9, 10, 11, 13, 14, 15, 16, 17, 18, 20, 21, 22, 24, 25, 26, 27, 28, 29, 31}
ORIGEM_MAP = {1: "Site", 2: "Marketplace", 3: "Manual", 4: "PDV"}
RECOMPRA_JANELA_DIAS = 180


def setup_logger(output_dir: Path) -> logging.Logger:
    """Configura log em console e arquivo dentro da pasta de relatorios."""
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("analise_recompra")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(output_dir / "analise_recompra.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def pick(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Retorna o primeiro campo preenchido encontrado no dicionario informado."""
    for name in names:
        if not isinstance(row, dict):
            continue
        if "." in name:
            current: Any = row
            for part in name.split("."):
                if not isinstance(current, dict) or part not in current:
                    current = None
                    break
                current = current.get(part)
            value = current
        else:
            value = row.get(name)
        if value not in (None, ""):
            return value
    return default


def normalize_text(value: Any) -> str:
    """Normaliza texto para comparacoes tolerantes a acentos e caixa."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().strip()


def to_float(value: Any) -> float:
    """Converte valores monetarios comuns da API para float."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float, np.number)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text.replace(".", "").replace(",", ".") if "," in text else text)
    except ValueError:
        return 0.0


def to_int(value: Any) -> int | None:
    """Converte valores numericos em inteiro quando possivel."""
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_datetime_naive(value: Any) -> pd.Timestamp | pd.NaT:
    """Converte datas da API para timestamp timezone-naive preservando o calendario local."""
    if value in (None, ""):
        return pd.NaT
    text = str(value).strip()
    timestamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(timestamp):
        return pd.NaT
    if getattr(timestamp, "tzinfo", None) is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp


def is_valid_order_status(row: pd.Series) -> bool:
    """Valida se o pedido representa compra operacionalmente valida para CRM."""
    code = to_int(row.get("status_codigo"))
    status = normalize_text(row.get("status_pedido"))
    status_detail = normalize_text(row.get("status_detalhado"))
    combined = f"{status} {status_detail}"

    if code in VALID_STATUS_CODES:
        return True
    if code in INVALID_STATUS_CODES:
        return False

    invalid_terms = (
        "cancel",
        "reprov",
        "devolv",
        "chargeback",
        "fraude",
        "disputa",
        "deneg",
        "aguardando pagamento",
        "em analise",
        "suspenso",
    )
    valid_terms = (
        "aprov",
        "fatur",
        "nota fiscal emitida",
        "transporte",
        "entreg",
        "conclu",
        "finaliz",
    )
    if any(term in combined for term in invalid_terms):
        return False
    return any(term in combined for term in valid_terms)


def map_order(row: dict[str, Any]) -> dict[str, Any]:
    """Mapeia um pedido bruto da API para o schema minimo da analise."""
    origem_codigo = to_int(pick(row, "origem", "origemCodigo"))
    canal = pick(
        row,
        "marketplaceNome",
        "lojaDoMarketplaceNome",
        "lojaMarketplaceNome",
        "canal",
        "canalVenda",
        default=ORIGEM_MAP.get(origem_codigo, "Nao informado"),
    )
    return {
        "pedido_id": pick(row, "id", "codigo", "codigoPedido", "pedido"),
        "cliente_id": pick(row, "pessoaId", "cliente_id", "clienteId", "idCliente", "pessoa.id"),
        "data_pedido": parse_datetime_naive(pick(row, "dataHora", "data", "dataEmissao", "dataPedido")),
        "valor_pedido": to_float(pick(row, "valorTotalFinal", "valorTotal", "total", "valor", "valorPedido")),
        "status_pedido": pick(row, "pedidoSituacaoDescricao", "situacaoDescricao", "status", "statusPedido"),
        "status_codigo": pick(row, "pedidoSituacao", "situacao", "statusCodigo"),
        "status_tipo": pick(row, "pedidoSituacaoTipo", "situacaoTipo"),
        "status_detalhado": pick(row, "pedidoSituacaoDescricaoDetalhada", "situacaoDescricaoDetalhada"),
        "canal": canal,
        "campanha": pick(row, "campanha", "pedidoTrackingCampaign", "utm_campaign"),
        "cupom": pick(row, "cupomCodigo", "cupom", "coupon"),
        "origem": pick(row, "pedidoTrackingSource", "origem", "source", default=ORIGEM_MAP.get(origem_codigo)),
        "midia": pick(row, "pedidoTrackingMedium", "midia", "utm_medium"),
    }


def map_customer(row: dict[str, Any]) -> dict[str, Any]:
    """Mapeia um cliente bruto da API para o schema minimo da analise."""
    return {
        "cliente_id": pick(row, "id", "pessoaId", "cliente_id", "clienteId"),
        "data_cadastro": parse_datetime_naive(pick(row, "dataCadastro", "createdAt", "dataCriacao")),
    }


def coletar_dados_api(start: date, end: date, logger: logging.Logger) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coleta historico completo de pedidos e cadastro de clientes diretamente da API configurada."""
    logger.info("Etapa 1 - Coleta via API de %s ate %s", start.isoformat(), end.isoformat())
    settings = load_settings(require_credentials=True)
    client = MagazordClient(settings.base_url, settings.api_key, settings.api_secret, logger)

    pedidos_raw = client.buscar_pedidos(start, end).rows
    clientes_raw = client.buscar_clientes(start, end).rows
    logger.info("Total bruto de pedidos coletados: %s", len(pedidos_raw))
    logger.info("Total bruto de clientes coletados: %s", len(clientes_raw))

    if pedidos_raw:
        sample_orders = pd.DataFrame(pedidos_raw[:5])
        logger.info("Amostra visual de campos de pedidos: %s", list(sample_orders.columns))
        logger.info("Amostra mapeada de pedidos:\n%s", pd.DataFrame([map_order(row) for row in pedidos_raw[:5]]).to_string(index=False))
    if clientes_raw:
        sample_customers = pd.DataFrame(clientes_raw[:5])
        logger.info("Amostra visual de campos de clientes: %s", list(sample_customers.columns))
        logger.info("Amostra mapeada de clientes:\n%s", pd.DataFrame([map_customer(row) for row in clientes_raw[:5]]).to_string(index=False))

    pedidos = pd.DataFrame([map_order(row) for row in pedidos_raw])
    clientes = pd.DataFrame([map_customer(row) for row in clientes_raw])

    if pedidos.empty:
        raise RuntimeError("A API nao retornou pedidos para o periodo solicitado.")

    pedidos = pedidos.dropna(subset=["cliente_id", "data_pedido"])
    pedidos["cliente_id"] = pedidos["cliente_id"].astype(str)
    pedidos["pedido_valido"] = pedidos.apply(is_valid_order_status, axis=1)
    pedidos_validos = pedidos[pedidos["pedido_valido"]].copy()
    pedidos_validos = pedidos_validos[pedidos_validos["valor_pedido"] >= 0].copy()

    if not clientes.empty:
        clientes = clientes.dropna(subset=["cliente_id"]).copy()
        clientes["cliente_id"] = clientes["cliente_id"].astype(str)

    logger.info("Total de pedidos validos apos filtro: %s", len(pedidos_validos))
    logger.info("Total de clientes unicos coletados: %s", clientes["cliente_id"].nunique() if not clientes.empty else 0)
    logger.info("Total de clientes compradores unicos nos pedidos validos: %s", pedidos_validos["cliente_id"].nunique())
    logger.info("Periodo minimo dos pedidos validos: %s", pedidos_validos["data_pedido"].min())
    logger.info("Periodo maximo dos pedidos validos: %s", pedidos_validos["data_pedido"].max())
    return pedidos_validos, clientes


def classificar_recompras(pedidos: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """Classifica cada pedido valido como primeira compra ou recompra dentro da janela de 180 dias."""
    logger.info("Etapa 2 - Classificacao de pedidos em primeira compra e recompra com janela de %s dias", RECOMPRA_JANELA_DIAS)
    df = pedidos.copy()
    df = df.sort_values(["cliente_id", "data_pedido", "pedido_id"], kind="mergesort").reset_index(drop=True)
    df["ordem_compra_cliente"] = df.groupby("cliente_id").cumcount() + 1
    df["data_compra_anterior"] = df.groupby("cliente_id")["data_pedido"].shift(1)
    df["dias_desde_compra_anterior"] = (df["data_pedido"] - df["data_compra_anterior"]).dt.days
    df["eh_primeira_compra"] = df["ordem_compra_cliente"].eq(1)
    df["eh_recompra"] = df["dias_desde_compra_anterior"].between(0, RECOMPRA_JANELA_DIAS, inclusive="both")
    df["fora_janela_recompra"] = df["ordem_compra_cliente"].gt(1) & ~df["eh_recompra"]
    df["ano_mes"] = df["data_pedido"].dt.to_period("M").astype(str)
    logger.info("Pedidos classificados: %s", len(df))
    logger.info("Recompras dentro de %s dias: %s", RECOMPRA_JANELA_DIAS, int(df["eh_recompra"].sum()))
    logger.info("Pedidos com historico anterior fora da janela de recompra: %s", int(df["fora_janela_recompra"].sum()))
    return df


def agregar_mensal(pedidos: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """Agrega as metricas mensais de compradores, recompradores e receita."""
    logger.info("Etapa 3 - Agregacao mensal")
    grouped = pedidos.groupby("ano_mes", sort=True)
    mensal = grouped.agg(
        total_pedidos=("pedido_id", "count"),
        compradores_unicos=("cliente_id", "nunique"),
        receita_total=("valor_pedido", "sum"),
    ).reset_index()

    recompras = pedidos[pedidos["eh_recompra"]]
    aquisicao_ou_reativacao = pedidos[~pedidos["eh_recompra"]]
    recompras_mensal = recompras.groupby("ano_mes").agg(
        recompradores=("cliente_id", "nunique"),
        receita_recompradores=("valor_pedido", "sum"),
        ticket_medio_recompradores=("valor_pedido", "mean"),
    )
    novos_mensal = aquisicao_ou_reativacao.groupby("ano_mes").agg(
        novos_clientes=("cliente_id", "nunique"),
        ticket_medio_novos=("valor_pedido", "mean"),
    )

    mensal = mensal.merge(recompras_mensal, on="ano_mes", how="left")
    mensal = mensal.merge(novos_mensal, on="ano_mes", how="left")
    for column in ("recompradores", "novos_clientes"):
        mensal[column] = mensal[column].fillna(0).astype(int)
    for column in ("receita_recompradores", "ticket_medio_recompradores", "ticket_medio_novos"):
        mensal[column] = mensal[column].fillna(0.0)
    mensal["taxa_recompra"] = np.where(
        mensal["compradores_unicos"] > 0,
        mensal["recompradores"] / mensal["compradores_unicos"],
        0.0,
    )
    logger.info("Meses agregados: %s", len(mensal))
    return mensal


def analisar_tendencia(mensal: pd.DataFrame, logger: logging.Logger) -> dict[str, Any]:
    """Analisa tendencia, variacao historica, sazonalidade e volatilidade de recompradores."""
    logger.info("Etapa 4 - Analise de tendencia e sazonalidade")
    serie = mensal[["ano_mes", "recompradores"]].copy()
    serie["periodo"] = pd.PeriodIndex(serie["ano_mes"], freq="M")
    serie = serie.sort_values("periodo").reset_index(drop=True)
    serie["mom"] = serie["recompradores"].pct_change()
    serie["yoy"] = serie["recompradores"] / serie["recompradores"].shift(12) - 1

    ultimos_12 = serie.tail(12)
    variacao_media_12 = float(ultimos_12["mom"].replace([np.inf, -np.inf], np.nan).dropna().mean()) if len(ultimos_12) > 1 else 0.0
    volatilidade_12 = float(ultimos_12["mom"].replace([np.inf, -np.inf], np.nan).dropna().std(ddof=0) or 0.0)
    yoy_medio = float(serie["yoy"].replace([np.inf, -np.inf], np.nan).dropna().tail(12).mean() or 0.0)

    if variacao_media_12 > 0.10:
        crescimento_base = min(variacao_media_12, 0.25)
    elif variacao_media_12 >= -0.05:
        crescimento_base = 0.15
    else:
        crescimento_base = 0.10

    if variacao_media_12 > 0.10 and yoy_medio > 0.10:
        tendencia = "crescimento acelerado"
    elif variacao_media_12 < -0.05 and yoy_medio < 0:
        tendencia = "queda"
    else:
        tendencia = "estavel"

    serie["mes"] = serie["periodo"].dt.month
    sazonalidade = serie.groupby("mes")["recompradores"].mean()
    media_geral = float(serie["recompradores"].mean() or 0.0)
    sazonal_index = (sazonalidade / media_geral).replace([np.inf, -np.inf], np.nan).fillna(1.0) if media_geral else sazonalidade * 0 + 1
    picos = sazonal_index[sazonal_index > 1.10].sort_values(ascending=False).index.tolist()
    vales = sazonal_index[sazonal_index < 0.90].sort_values().index.tolist()

    logger.info("Variacao media MoM ultimos 12 meses: %.2f%%", variacao_media_12 * 100)
    logger.info("Variacao YoY media disponivel: %.2f%%", yoy_medio * 100)
    logger.info("Volatilidade mensal: %.2f%%", volatilidade_12 * 100)
    logger.info("Tendencia geral: %s", tendencia)
    logger.info("Meses historicamente fortes: %s", ", ".join(f"{m:02d}" for m in picos) or "nenhum claro")
    logger.info("Meses historicamente fracos: %s", ", ".join(f"{m:02d}" for m in vales) or "nenhum claro")

    return {
        "serie": serie,
        "variacao_media_12": variacao_media_12,
        "volatilidade_12": volatilidade_12,
        "yoy_medio": yoy_medio,
        "crescimento_base": crescimento_base,
        "tendencia": tendencia,
        "sazonal_index": sazonal_index.to_dict(),
        "picos": picos,
        "vales": vales,
    }


def format_pct(value: float) -> str:
    """Formata percentual para textos de justificativa."""
    return f"{value * 100:.1f}%"


def calcular_metas(mensal: pd.DataFrame, tendencia: dict[str, Any], logger: logging.Logger) -> pd.DataFrame:
    """Calcula metas mensais automaticas com baseline YoY ou media movel de tres meses."""
    logger.info("Etapa 4 - Calculo de metas mensais automaticas")
    df = mensal.copy()
    df["periodo"] = pd.PeriodIndex(df["ano_mes"], freq="M")
    df = df.sort_values("periodo").reset_index(drop=True)
    recompras_por_periodo = dict(zip(df["periodo"], df["recompradores"], strict=False))

    metas = []
    crescimento_base = float(tendencia["crescimento_base"])
    volatilidade = float(tendencia["volatilidade_12"])
    sazonal_index = tendencia["sazonal_index"]
    ajuste_moderador = max(0.35, 1 - min(volatilidade, 0.65))

    for idx, row in df.iterrows():
        periodo = row["periodo"]
        mes = periodo.month
        yoy_periodo = periodo - 12
        yoy_value = recompras_por_periodo.get(yoy_periodo)
        if yoy_value is not None and not pd.isna(yoy_value):
            baseline = float(yoy_value)
            baseline_label = f"mesmo mes do ano anterior ({yoy_periodo})"
        else:
            historico_3m = df.loc[: idx - 1, "recompradores"].tail(3)
            baseline = float(historico_3m.mean()) if not historico_3m.empty else float(row["recompradores"])
            baseline_label = "media dos ultimos 3 meses disponiveis" if not historico_3m.empty else "proprio primeiro mes disponivel"

        sazonal = float(sazonal_index.get(mes, 1.0))
        ajuste_sazonal = (sazonal - 1.0) * 0.50 * ajuste_moderador
        crescimento_alvo = max(0.02, min(0.35, crescimento_base * (1 + ajuste_sazonal)))
        faixa_minima = baseline * (1 + crescimento_alvo * 0.90)
        meta_base = baseline * (1 + crescimento_alvo)
        meta_stretch = baseline * (1 + crescimento_alvo * 1.10)
        realizado = float(row["recompradores"])
        percentual = (realizado / meta_base * 100) if meta_base else 0.0
        status = "abaixo" if percentual < 90 else "stretch" if percentual > 110 else "atingido"

        if sazonal >= 1.10:
            sazonal_txt = f"mes historicamente forte, indice sazonal {sazonal:.2f}"
        elif sazonal <= 0.90:
            sazonal_txt = f"mes historicamente fraco, indice sazonal {sazonal:.2f}"
        else:
            sazonal_txt = f"sazonalidade proxima da media, indice {sazonal:.2f}"

        justificativa = (
            f"Meta baseada em tendencia {tendencia['tendencia']} com variacao media recente de "
            f"{format_pct(tendencia['variacao_media_12'])}. O baseline usado foi {baseline_label}, "
            f"com {baseline:.1f} recompradores. O crescimento alvo final foi {format_pct(crescimento_alvo)}, "
            f"partindo da regra automatica de {format_pct(crescimento_base)} e ajustado por {sazonal_txt}; "
            f"a volatilidade mensal de {format_pct(volatilidade)} moderou o ajuste."
        )

        metas.append(
            {
                "ano_mes": row["ano_mes"],
                "baseline_yoy": int(round(baseline)),
                "crescimento_alvo_pct": int(round(crescimento_alvo * 100)),
                "meta_base": int(round(meta_base)),
                "faixa_minima": int(round(faixa_minima)),
                "meta_stretch": int(round(meta_stretch)),
                "recompradores_realizados": int(row["recompradores"]),
                "percentual_atingimento": int(round(percentual)),
                "status": status,
                "justificativa": justificativa,
            }
        )

    metas_df = pd.DataFrame(metas)
    logger.info("Metas calculadas para %s meses", len(metas_df))
    return metas_df


def identificar_inativos(pedidos: pd.DataFrame, referencia: date, logger: logging.Logger) -> pd.DataFrame:
    """Identifica clientes compradores sem recompra recente e segmenta faixas de inatividade."""
    logger.info("Etapa 6 - Identificacao de inativos recuperaveis")
    ultimas = pedidos.groupby("cliente_id", as_index=False).agg(data_ultima_compra=("data_pedido", "max"))
    ref_ts = pd.Timestamp(referencia)
    ultimas["dias_inativo"] = (ref_ts - ultimas["data_ultima_compra"]).dt.days
    inativos = ultimas[ultimas["dias_inativo"] >= 90].copy()
    inativos["faixa_inatividade"] = np.where(inativos["dias_inativo"] >= 180, "180d", "90d")
    inativos["data_ultima_compra"] = inativos["data_ultima_compra"].dt.date.astype(str)
    inativos = inativos.sort_values(["faixa_inatividade", "dias_inativo", "cliente_id"], ascending=[True, False, True])
    logger.info("Inativos 90d: %s", int((inativos["faixa_inatividade"] == "90d").sum()))
    logger.info("Inativos 180d: %s", int((inativos["faixa_inatividade"] == "180d").sum()))
    return inativos[["cliente_id", "data_ultima_compra", "dias_inativo", "faixa_inatividade"]]


def build_metodologia(tendencia: dict[str, Any], metas: pd.DataFrame) -> str:
    """Gera documento de metodologia em linguagem nao tecnica."""
    justificativas = "\n".join(
        f"- {row.ano_mes}: {row.justificativa}" for row in metas.itertuples(index=False)
    )
    return f"""# Metodologia da meta de recompradores

## Dados usados

A analise usou pedidos e clientes coletados diretamente da API configurada no projeto. Antes dos calculos, os pedidos foram filtrados para manter somente situacoes operacionais validas, como aprovado, faturado, em transporte, entregue ou equivalentes. Pedidos cancelados, reprovados, em analise, devolvidos integralmente, chargeback, fraude ou nota fiscal cancelada foram removidos.

## Como recompradores foram classificados

Para cada cliente, os pedidos validos foram ordenados por data. O primeiro pedido valido foi classificado como primeira compra. Um pedido posterior so foi classificado como recompra quando ocorreu em ate 180 dias depois da compra valida anterior. Essa janela reflete a frequencia media do negocio, de 2 a 3 compras por ano, e evita contar como recompra um cliente antigo que voltou depois de muito tempo e provavelmente exigiu novo esforco de aquisicao ou reativacao.

## Como a tendencia historica foi identificada

A serie mensal de recompradores foi analisada pela variacao mes a mes dos ultimos 12 meses disponiveis, pela variacao contra o mesmo mes do ano anterior quando havia dados, e pela volatilidade mensal. A tendencia geral encontrada foi **{tendencia['tendencia']}**, com variacao media recente de **{format_pct(tendencia['variacao_media_12'])}** e volatilidade de **{format_pct(tendencia['volatilidade_12'])}**.

## Como o baseline foi escolhido

O baseline principal de cada mes foi o mesmo mes do ano anterior. Quando esse dado nao existia, a meta usou a media dos ultimos tres meses disponiveis. No primeiro mes da serie, quando nao havia historico anterior suficiente, o proprio resultado do mes foi usado apenas como ponto inicial.

## Como a sazonalidade ajustou a meta

Cada mes recebeu um indice sazonal calculado pela media historica daquele mes em relacao a media geral. Meses acima da media receberam metas proporcionalmente mais altas. Meses abaixo da media receberam metas mais baixas. Quando a volatilidade era alta, o ajuste sazonal foi moderado para evitar metas excessivamente agressivas ou frouxas.

## Significado das faixas

- Faixa minima: nivel de entrega aceitavel para acompanhamento, equivalente a 90% do crescimento alvo aplicado sobre o baseline.
- Meta base: alvo principal usado para avaliar o atingimento mensal.
- Stretch: alvo superior, equivalente a 110% do crescimento alvo aplicado sobre o baseline.

## Como interpretar o status

- abaixo: resultado menor que 90% da meta base.
- atingido: resultado entre 90% e 110% da meta base.
- stretch: resultado acima de 110% da meta base.

## Justificativa mensal das metas

{justificativas}
"""


def exportar_relatorios(
    mensal: pd.DataFrame,
    metas: pd.DataFrame,
    inativos: pd.DataFrame,
    tendencia: dict[str, Any],
    output_dir: Path,
    logger: logging.Logger,
) -> dict[str, Path]:
    """Exporta CSVs, JSON de dashboard e metodologia em Markdown."""
    logger.info("Etapa 7 - Exportacao dos relatorios")
    output_dir.mkdir(parents=True, exist_ok=True)

    mensal_cols = [
        "ano_mes",
        "total_pedidos",
        "compradores_unicos",
        "recompradores",
        "novos_clientes",
        "taxa_recompra",
        "receita_total",
        "receita_recompradores",
        "ticket_medio_recompradores",
        "ticket_medio_novos",
    ]
    metas_cols = [
        "ano_mes",
        "baseline_yoy",
        "crescimento_alvo_pct",
        "meta_base",
        "faixa_minima",
        "meta_stretch",
        "recompradores_realizados",
        "percentual_atingimento",
        "status",
        "justificativa",
    ]

    paths = {
        "recompradores_mensal": output_dir / "recompradores_mensal.csv",
        "metas_mensais": output_dir / "metas_mensais.csv",
        "inativos_recuperaveis": output_dir / "inativos_recuperaveis.csv",
        "resumo_dashboard": output_dir / "resumo_dashboard.json",
        "metodologia_meta": output_dir / "metodologia_meta.md",
    }

    mensal_export = mensal[mensal_cols].copy()
    for column in (
        "receita_total",
        "receita_recompradores",
        "ticket_medio_recompradores",
        "ticket_medio_novos",
    ):
        mensal_export[column] = mensal_export[column].round(0).astype(int)
    mensal_export["taxa_recompra"] = (mensal_export["taxa_recompra"] * 100).round(0).astype(int)

    metas_export = metas[metas_cols].copy()
    for column in (
        "baseline_yoy",
        "crescimento_alvo_pct",
        "meta_base",
        "faixa_minima",
        "meta_stretch",
        "recompradores_realizados",
        "percentual_atingimento",
    ):
        metas_export[column] = metas_export[column].round(0).astype(int)

    mensal_export.to_csv(paths["recompradores_mensal"], index=False, encoding="utf-8-sig")
    metas_export.to_csv(paths["metas_mensais"], index=False, encoding="utf-8-sig")
    inativos.to_csv(paths["inativos_recuperaveis"], index=False, encoding="utf-8-sig")

    ultimo_mes = metas.iloc[-1]
    mensal_ultimo = mensal[mensal["ano_mes"] == ultimo_mes["ano_mes"]].iloc[0]
    resumo = {
        "ano_mes": str(ultimo_mes["ano_mes"]),
        "recompradores": int(mensal_ultimo["recompradores"]),
        "meta_base": int(ultimo_mes["meta_base"]),
        "percentual_atingimento": int(ultimo_mes["percentual_atingimento"]),
        "status": str(ultimo_mes["status"]),
        "novos_clientes": int(mensal_ultimo["novos_clientes"]),
        "taxa_recompra": int(round(float(mensal_ultimo["taxa_recompra"]) * 100)),
        "crescimento_alvo_pct": int(ultimo_mes["crescimento_alvo_pct"]),
        "total_inativos_90d": int((inativos["faixa_inatividade"] == "90d").sum()) if not inativos.empty else 0,
        "total_inativos_180d": int((inativos["faixa_inatividade"] == "180d").sum()) if not inativos.empty else 0,
    }
    paths["resumo_dashboard"].write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["metodologia_meta"].write_text(build_metodologia(tendencia, metas), encoding="utf-8")

    for name, path in paths.items():
        logger.info("Arquivo gerado %s: %s", name, path)
    return paths


def parse_args() -> argparse.Namespace:
    """Le argumentos da linha de comando."""
    parser = argparse.ArgumentParser(description="Analise de recompradores, metas mensais e inativos recuperaveis.")
    parser.add_argument("--output", default="./relatorios", help="Pasta de saida dos relatorios.")
    parser.add_argument("--start", default="2000-01-01", help="Data inicial da coleta API no formato YYYY-MM-DD.")
    parser.add_argument("--end", default=date.today().isoformat(), help="Data final da coleta API no formato YYYY-MM-DD.")
    return parser.parse_args()


def main() -> None:
    """Executa o pipeline completo de analise de recompradores."""
    args = parse_args()
    output_dir = Path(args.output).resolve()
    logger = setup_logger(output_dir)
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    if requests is None or pd is None or np is None or math is None:
        raise RuntimeError("Dependencias obrigatorias indisponiveis.")

    pedidos_validos, clientes = coletar_dados_api(start, end, logger)
    pedidos_classificados = classificar_recompras(pedidos_validos, logger)
    mensal = agregar_mensal(pedidos_classificados, logger)
    tendencia = analisar_tendencia(mensal, logger)
    metas = calcular_metas(mensal, tendencia, logger)
    inativos = identificar_inativos(pedidos_classificados, end, logger)
    paths = exportar_relatorios(mensal, metas, inativos, tendencia, output_dir, logger)

    ultimo_mes = metas.iloc[-1]
    periodo_min = pedidos_classificados["data_pedido"].min().date()
    periodo_max = pedidos_classificados["data_pedido"].max().date()
    print("\nResumo final")
    print(f"Total de pedidos validos analisados: {len(pedidos_classificados)}")
    print(f"Total de clientes compradores unicos: {pedidos_classificados['cliente_id'].nunique()}")
    print(f"Periodo analisado: {periodo_min} a {periodo_max}")
    print(f"Mes mais recente: {ultimo_mes['ano_mes']}")
    print(f"Recompradores do mes mais recente: {int(ultimo_mes['recompradores_realizados'])}")
    print(f"Meta base do mes mais recente: {int(ultimo_mes['meta_base'])}")
    print(f"Percentual de atingimento: {int(ultimo_mes['percentual_atingimento'])}%")
    print(f"Status: {ultimo_mes['status']}")
    print("Arquivos gerados:")
    for path in paths.values():
        print(f"- {path}")


if __name__ == "__main__":
    main()
