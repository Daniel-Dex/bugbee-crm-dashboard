from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from analise_recompra import (
    RECOMPRA_JANELA_DIAS,
    agregar_mensal,
    classificar_recompras,
    coletar_dados_api,
    setup_logger,
)


RFM_PERIODO_DIAS = 365
FUTURE_PLAN = [
    {"ano_mes": "2026-06", "mes": "Junho", "meta_pedidos": 1391, "meta_receita_liquida": 500850},
    {"ano_mes": "2026-07", "mes": "Julho", "meta_pedidos": 1886, "meta_receita_liquida": 867510},
    {"ano_mes": "2026-08", "mes": "Agosto", "meta_pedidos": 628, "meta_receita_liquida": 251370},
    {"ano_mes": "2026-09", "mes": "Setembro", "meta_pedidos": 1218, "meta_receita_liquida": 548100},
    {"ano_mes": "2026-10", "mes": "Outubro", "meta_pedidos": 822, "meta_receita_liquida": 328860},
    {"ano_mes": "2026-11", "mes": "Novembro", "meta_pedidos": 4401, "meta_receita_liquida": 1540350},
    {"ano_mes": "2026-12", "mes": "Dezembro", "meta_pedidos": 656, "meta_receita_liquida": 209790},
]


@dataclass(frozen=True)
class ProjectionResult:
    historico_mensal: pd.DataFrame
    metas_futuras: pd.DataFrame
    rfm_clientes: pd.DataFrame
    clientes_priorizados: pd.DataFrame
    resumo_rfm: pd.DataFrame
    metodologia: dict


def safe_quantile_score(series: pd.Series, high_is_good: bool = True) -> pd.Series:
    """Cria score de 1 a 5 por quintis, com fallback robusto para bases pequenas ou empatadas."""
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    if values.nunique() <= 1:
        return pd.Series(np.full(len(values), 3), index=series.index)
    ranked = values.rank(method="first")
    labels = [1, 2, 3, 4, 5] if high_is_good else [5, 4, 3, 2, 1]
    return pd.qcut(ranked, 5, labels=labels).astype(int)


def month_start(ano_mes: str) -> pd.Timestamp:
    """Retorna o primeiro dia do mes informado em YYYY-MM."""
    return pd.Period(ano_mes, freq="M").to_timestamp()


def calcular_rfm(pedidos: pd.DataFrame, data_referencia: pd.Timestamp, logger: logging.Logger) -> pd.DataFrame:
    """Calcula Recencia, Frequencia e Valor por cliente usando periodo de analise de 365 dias."""
    logger.info("Calculando RFM com periodo de %s dias e referencia %s", RFM_PERIODO_DIAS, data_referencia.date())
    inicio_periodo = data_referencia - pd.Timedelta(days=RFM_PERIODO_DIAS)
    ultimos_365 = pedidos[pedidos["data_pedido"] >= inicio_periodo].copy()

    base = pedidos.groupby("cliente_id").agg(
        primeira_compra=("data_pedido", "min"),
        ultima_compra=("data_pedido", "max"),
        frequencia_total=("pedido_id", "count"),
        valor_total=("valor_pedido", "sum"),
    )
    recente = ultimos_365.groupby("cliente_id").agg(
        frequencia_365d=("pedido_id", "count"),
        valor_365d=("valor_pedido", "sum"),
    )
    rfm = base.join(recente, how="left").fillna({"frequencia_365d": 0, "valor_365d": 0}).reset_index()
    rfm["recencia_dias"] = (data_referencia - rfm["ultima_compra"]).dt.days.clip(lower=0)
    rfm["score_recencia"] = pd.cut(
        rfm["recencia_dias"],
        bins=[-1, 30, 60, 120, RECOMPRA_JANELA_DIAS, 10_000],
        labels=[5, 4, 3, 2, 1],
    ).astype(int)
    rfm["score_frequencia"] = safe_quantile_score(rfm["frequencia_365d"], high_is_good=True)
    rfm["score_valor"] = safe_quantile_score(rfm["valor_365d"], high_is_good=True)
    rfm["score_rfm"] = (
        rfm["score_recencia"] * 0.45
        + rfm["score_frequencia"] * 0.35
        + rfm["score_valor"] * 0.20
    ).round(2)
    rfm["segmento_rfm"] = np.select(
        [
            (rfm["recencia_dias"] <= 60) & (rfm["score_frequencia"] >= 4),
            (rfm["recencia_dias"] <= RECOMPRA_JANELA_DIAS) & (rfm["score_rfm"] >= 3.5),
            (rfm["recencia_dias"] <= RECOMPRA_JANELA_DIAS),
            (rfm["recencia_dias"] > RECOMPRA_JANELA_DIAS) & (rfm["recencia_dias"] <= 365),
        ],
        ["alta propensao", "boa propensao", "a nutrir", "reativacao"],
        default="frio",
    )
    return rfm


def analisar_ciclo_compra(pedidos: pd.DataFrame) -> dict:
    """Calcula intervalos reais entre compras para justificar a janela de positivacao."""
    df = pedidos.sort_values(["cliente_id", "data_pedido"]).copy()
    df["compra_anterior"] = df.groupby("cliente_id")["data_pedido"].shift(1)
    df["intervalo_dias"] = (df["data_pedido"] - df["compra_anterior"]).dt.days
    intervalos = df["intervalo_dias"].dropna()
    intervalos_positivos = intervalos[intervalos > 0]
    return {
        "intervalos_observados": int(len(intervalos_positivos)),
        "mediana_intervalo_dias": int(round(intervalos_positivos.median())) if not intervalos_positivos.empty else 0,
        "media_intervalo_dias": int(round(intervalos_positivos.mean())) if not intervalos_positivos.empty else 0,
        "pct_ate_180d": int(round((intervalos_positivos.le(180).mean() * 100))) if not intervalos_positivos.empty else 0,
    }


def projetar_metas(
    historico: pd.DataFrame,
    rfm: pd.DataFrame,
    data_referencia: pd.Timestamp,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Projeta positivacao por mes combinando metas enviadas, sazonalidade historica e pool RFM elegivel."""
    hist = historico.copy()
    hist["periodo"] = pd.PeriodIndex(hist["ano_mes"], freq="M")
    hist["mes_num"] = hist["periodo"].dt.month
    hist["compradores_por_pedido"] = np.where(hist["total_pedidos"] > 0, hist["compradores_unicos"] / hist["total_pedidos"], 0)
    hist["taxa_recompra_decimal"] = np.where(hist["compradores_unicos"] > 0, hist["recompradores"] / hist["compradores_unicos"], 0)

    media_compradores_pedido = float(hist.tail(12)["compradores_por_pedido"].mean())
    media_taxa_12m = float(hist.tail(12)["taxa_recompra_decimal"].mean())
    taxa_por_mes = hist.groupby("mes_num")["taxa_recompra_decimal"].mean().to_dict()
    compradores_pedido_por_mes = hist.groupby("mes_num")["compradores_por_pedido"].mean().to_dict()

    usados: set[str] = set()
    clientes_priorizados = []
    linhas = []

    for plan in FUTURE_PLAN:
        inicio_mes = month_start(plan["ano_mes"])
        mes_num = int(inicio_mes.month)
        compradores_ratio = compradores_pedido_por_mes.get(mes_num, media_compradores_pedido) or media_compradores_pedido
        compradores_projetados = int(round(plan["meta_pedidos"] * compradores_ratio))
        taxa_mes = float(taxa_por_mes.get(mes_num, media_taxa_12m) or media_taxa_12m)
        taxa_projetada = float((taxa_mes * 0.65) + (media_taxa_12m * 0.35))
        meta_positivacao = int(round(compradores_projetados * taxa_projetada))

        pool = rfm[
            (rfm["ultima_compra"] < inicio_mes)
            & ((inicio_mes - rfm["ultima_compra"]).dt.days <= RECOMPRA_JANELA_DIAS)
            & (~rfm["cliente_id"].astype(str).isin(usados))
        ].copy()
        pool["dias_no_inicio_mes"] = (inicio_mes - pool["ultima_compra"]).dt.days
        pool["mes_recomendado"] = plan["ano_mes"]
        pool = pool.sort_values(
            ["score_rfm", "score_recencia", "frequencia_365d", "valor_365d", "dias_no_inicio_mes"],
            ascending=[False, False, False, False, True],
        )
        selecionados = pool.head(meta_positivacao).copy()
        usados.update(selecionados["cliente_id"].astype(str).tolist())
        clientes_priorizados.append(selecionados)

        linhas.append(
            {
                "ano_mes": plan["ano_mes"],
                "mes": plan["mes"],
                "meta_pedidos": int(plan["meta_pedidos"]),
                "meta_receita_liquida": int(plan["meta_receita_liquida"]),
                "compradores_projetados": compradores_projetados,
                "taxa_recompra_proj_pct": int(round(taxa_projetada * 100)),
                "meta_positivacao_clientes": meta_positivacao,
                "pool_elegivel_180d": int(len(pool)),
                "clientes_priorizados": int(len(selecionados)),
                "cobertura_pool_pct": int(round((len(selecionados) / len(pool) * 100))) if len(pool) else 0,
            }
        )

    clientes_df = pd.concat(clientes_priorizados, ignore_index=True) if clientes_priorizados else pd.DataFrame()
    keep_cols = [
        "cliente_id",
        "mes_recomendado",
        "ultima_compra",
        "dias_no_inicio_mes",
        "recencia_dias",
        "frequencia_365d",
        "valor_365d",
        "score_recencia",
        "score_frequencia",
        "score_valor",
        "score_rfm",
        "segmento_rfm",
    ]
    if not clientes_df.empty:
        clientes_df = clientes_df[keep_cols].copy()
        clientes_df["cliente_id"] = clientes_df["cliente_id"].astype(str)
        clientes_df["ultima_compra"] = pd.to_datetime(clientes_df["ultima_compra"]).dt.date.astype(str)
        for col in ["frequencia_365d", "valor_365d", "recencia_dias", "dias_no_inicio_mes"]:
            clientes_df[col] = clientes_df[col].round(0).astype(int)

    logger.info("Clientes priorizados unicos na projecao: %s", len(clientes_df))
    return pd.DataFrame(linhas), clientes_df


def gerar_resumo_rfm(rfm: pd.DataFrame) -> pd.DataFrame:
    """Resume a base RFM por segmento, com contagens e medias arredondadas."""
    resumo = rfm.groupby("segmento_rfm", as_index=False).agg(
        clientes=("cliente_id", "nunique"),
        recencia_media=("recencia_dias", "mean"),
        frequencia_media_365d=("frequencia_365d", "mean"),
        valor_medio_365d=("valor_365d", "mean"),
        score_medio=("score_rfm", "mean"),
    )
    for col in ["recencia_media", "frequencia_media_365d", "valor_medio_365d", "score_medio"]:
        resumo[col] = resumo[col].round(0).astype(int)
    return resumo.sort_values("clientes", ascending=False)


def exportar_projection(result: ProjectionResult, output_dir: Path, logger: logging.Logger) -> dict[str, Path]:
    """Exporta bases intermediarias da projecao para alimentar o workbook formatado."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "historico_mensal": output_dir / "historico_mensal_180d.csv",
        "metas_futuras": output_dir / "metas_positivacao_futuras.csv",
        "rfm_clientes": output_dir / "rfm_clientes.csv",
        "clientes_priorizados": output_dir / "clientes_priorizados_positivacao.csv",
        "resumo_rfm": output_dir / "resumo_rfm.csv",
        "metodologia": output_dir / "metodologia_projecao.json",
    }
    hist = result.historico_mensal.copy()
    for col in ["taxa_recompra"]:
        hist[col] = (hist[col] * 100).round(0).astype(int)
    for col in ["receita_total", "receita_recompradores", "ticket_medio_recompradores", "ticket_medio_novos"]:
        hist[col] = hist[col].round(0).astype(int)
    hist.to_csv(paths["historico_mensal"], index=False, encoding="utf-8-sig")
    result.metas_futuras.to_csv(paths["metas_futuras"], index=False, encoding="utf-8-sig")
    rfm_export = result.rfm_clientes.copy()
    rfm_export["ultima_compra"] = pd.to_datetime(rfm_export["ultima_compra"]).dt.date.astype(str)
    rfm_export["primeira_compra"] = pd.to_datetime(rfm_export["primeira_compra"]).dt.date.astype(str)
    for col in ["frequencia_total", "valor_total", "frequencia_365d", "valor_365d", "recencia_dias"]:
        rfm_export[col] = rfm_export[col].round(0).astype(int)
    rfm_export.to_csv(paths["rfm_clientes"], index=False, encoding="utf-8-sig")
    result.clientes_priorizados.to_csv(paths["clientes_priorizados"], index=False, encoding="utf-8-sig")
    result.resumo_rfm.to_csv(paths["resumo_rfm"], index=False, encoding="utf-8-sig")
    paths["metodologia"].write_text(json.dumps(result.metodologia, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, path in paths.items():
        logger.info("Arquivo de projecao gerado %s: %s", name, path)
    return paths


def executar(output_dir: Path, start: date, end: date) -> ProjectionResult:
    """Executa a projecao completa de positivacao futura com RFM e metas enviadas."""
    logger = setup_logger(output_dir)
    pedidos_validos, _clientes = coletar_dados_api(start, end, logger)
    pedidos_classificados = classificar_recompras(pedidos_validos, logger)
    historico = agregar_mensal(pedidos_classificados, logger)
    data_referencia = pedidos_classificados["data_pedido"].max().normalize()
    rfm = calcular_rfm(pedidos_classificados, data_referencia, logger)
    ciclo = analisar_ciclo_compra(pedidos_classificados)
    metas_futuras, clientes_priorizados = projetar_metas(historico, rfm, data_referencia, logger)
    resumo_rfm = gerar_resumo_rfm(rfm)
    metodologia = {
        "data_referencia": str(data_referencia.date()),
        "janela_positivacao_dias": RECOMPRA_JANELA_DIAS,
        "periodo_rfm_dias": RFM_PERIODO_DIAS,
        "criterio_cliente_unico": "cliente_id aparece no maximo uma vez na lista priorizada de meses futuros",
        "ciclo_compra": ciclo,
        "fonte_metas": "metas digitadas a partir da planilha/imagem enviada no chat para junho a dezembro de 2026",
        "observacao": "A taxa de recompra acompanha a meta, mas a bonificacao pode usar o numero inteiro de clientes positivados.",
    }
    return ProjectionResult(historico, metas_futuras, rfm, clientes_priorizados, resumo_rfm, metodologia)


def parse_args() -> argparse.Namespace:
    """Le argumentos CLI da projecao."""
    parser = argparse.ArgumentParser(description="Projeta positivacao futura com metas, historico e RFM.")
    parser.add_argument("--output", default="./relatorios/projecao_positivacao", help="Pasta de saida dos dados da projecao.")
    parser.add_argument("--start", default="2000-01-01", help="Data inicial da coleta API no formato YYYY-MM-DD.")
    parser.add_argument("--end", default=date.today().isoformat(), help="Data final da coleta API no formato YYYY-MM-DD.")
    return parser.parse_args()


def main() -> None:
    """Executa e exporta a projecao."""
    args = parse_args()
    output_dir = Path(args.output).resolve()
    result = executar(
        output_dir,
        pd.Timestamp(args.start).date(),
        pd.Timestamp(args.end).date(),
    )
    exportar_projection(result, output_dir, logging.getLogger("analise_recompra"))
    ultimo = result.metas_futuras.iloc[0]
    print("Resumo projecao")
    print(f"Primeiro mes projetado: {ultimo['ano_mes']}")
    print(f"Meta pedidos: {int(ultimo['meta_pedidos'])}")
    print(f"Meta positivacao clientes: {int(ultimo['meta_positivacao_clientes'])}")
    print(f"Taxa recompra projetada: {int(ultimo['taxa_recompra_proj_pct'])}%")
    print(f"Clientes priorizados unicos: {len(result.clientes_priorizados)}")
    print(f"Saida: {output_dir}")


if __name__ == "__main__":
    main()
