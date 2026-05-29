from __future__ import annotations

import argparse
import html
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from analise_recompra import (
    agregar_mensal,
    analisar_tendencia,
    calcular_metas,
    classificar_recompras,
    coletar_dados_api,
    setup_logger,
)
from projecao_positivacao import FUTURE_PLAN, calcular_rfm, projetar_metas


MONTHS = [
    ("01", "Janeiro"),
    ("02", "Fevereiro"),
    ("03", "Março"),
    ("04", "Abril"),
    ("05", "Maio"),
    ("06", "Junho"),
    ("07", "Julho"),
    ("08", "Agosto"),
    ("09", "Setembro"),
    ("10", "Outubro"),
    ("11", "Novembro"),
    ("12", "Dezembro"),
]


def pct(realizado: int, meta: int) -> int:
    """Calcula percentual inteiro de atingimento."""
    return int(round((realizado / meta) * 100)) if meta else 0


def status_color(atingimento: int) -> str:
    """Retorna classe visual para status de atingimento."""
    if atingimento >= 100:
        return "ok"
    if atingimento >= 80:
        return "warn"
    return "low"


def build_dashboard_data(start: date, end: date, logger: logging.Logger) -> dict:
    """Busca a API, calcula positivação 180d e prepara o painel mensal de metas CRM."""
    pedidos_validos, _clientes = coletar_dados_api(start, end, logger, include_customers=False, log_samples=False)
    classificados = classificar_recompras(pedidos_validos, logger)
    mensal = agregar_mensal(classificados, logger)
    tendencia = analisar_tendencia(mensal, logger)
    metas_hist = calcular_metas(mensal, tendencia, logger)

    data_referencia = classificados["data_pedido"].max().normalize()
    rfm = calcular_rfm(classificados, data_referencia, logger)
    metas_futuras, _clientes_priorizados = projetar_metas(mensal, rfm, data_referencia, logger)
    futuras_map = {
        row["ano_mes"]: int(row["meta_positivacao_clientes"])
        for _, row in metas_futuras.iterrows()
    }
    metas_hist_map = {
        row["ano_mes"]: int(row["meta_base"])
        for _, row in metas_hist.iterrows()
    }
    recompras_map = {
        row["ano_mes"]: int(row["recompradores"])
        for _, row in mensal.iterrows()
    }
    taxa_map = {
        row["ano_mes"]: int(round(float(row["taxa_recompra"]) * 100))
        for _, row in mensal.iterrows()
    }

    rows = []
    for month_number, month_name in MONTHS:
        key_2025 = f"2025-{month_number}"
        key_2026 = f"2026-{month_number}"
        realizado_2025 = recompras_map.get(key_2025, 0)
        realizado_2026 = recompras_map.get(key_2026, 0)
        meta = futuras_map.get(key_2026) or metas_hist_map.get(key_2026) or int(round(realizado_2025 * 1.15))
        atingimento = pct(realizado_2026, meta)
        rows.append(
            {
                "mes": month_name,
                "realizado_2025": realizado_2025,
                "meta": int(meta),
                "realizado_2026": realizado_2026,
                "taxa_recompra_2026": taxa_map.get(key_2026, 0),
                "atingimento": atingimento,
                "status": status_color(atingimento),
            }
        )

    total_realizado_2025 = sum(row["realizado_2025"] for row in rows)
    total_meta = sum(row["meta"] for row in rows)
    total_realizado_2026 = sum(row["realizado_2026"] for row in rows)
    compradores_2026 = mensal[mensal["ano_mes"].str.startswith("2026")]["compradores_unicos"].sum()
    taxa_total_2026 = int(round((total_realizado_2026 / compradores_2026) * 100)) if compradores_2026 else 0

    return {
        "updated_at": pd.Timestamp.now(tz="America/Bahia").strftime("%d/%m/%Y %H:%M"),
        "periodo_api": {
            "inicio": str(classificados["data_pedido"].min().date()),
            "fim": str(classificados["data_pedido"].max().date()),
        },
        "totals": {
            "realizado_2025": total_realizado_2025,
            "meta": total_meta,
            "realizado_2026": total_realizado_2026,
            "atingimento": pct(total_realizado_2026, total_meta),
            "taxa_recompra_2026": taxa_total_2026,
        },
        "rows": rows,
    }


def format_int(value: int) -> str:
    """Formata inteiro em pt-BR sem casas decimais."""
    return f"{int(value):,}".replace(",", ".")


def safe_text(value: object) -> str:
    """Escapa texto antes de inserir no HTML público."""
    return html.escape(str(value), quote=True)


def render_html(data: dict) -> str:
    """Renderiza o dashboard público com identidade Bugbee."""
    rows_html = "\n".join(
        f"""
        <tr class="{safe_text(row['status'])}">
          <td>{safe_text(row['mes'])}</td>
          <td>{format_int(row['realizado_2025'])}</td>
          <td>{format_int(row['meta'])}</td>
          <td>{format_int(row['realizado_2026'])}</td>
          <td>{row['taxa_recompra_2026']}%</td>
          <td>{row['atingimento']}%</td>
        </tr>
        """
        for row in data["rows"]
    )
    totals = data["totals"]
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow" />
  <meta http-equiv="refresh" content="900" />
  <title>Bugbee | Metas CRM</title>
  <style>
    @font-face {{
      font-family: "Rubrik";
      src: url("./fonts/Rubrik.otf") format("opentype");
      font-weight: 400;
    }}
    @font-face {{
      font-family: "Rubrik";
      src: url("./fonts/Rubrik SemiBold.otf") format("opentype");
      font-weight: 600;
    }}
    @font-face {{
      font-family: "Rubrik";
      src: url("./fonts/Rubrik Bold.otf") format("opentype");
      font-weight: 700;
    }}
    :root {{
      --ink: #073747;
      --ink-2: #0b4555;
      --orange: #aa4a1f;
      --cream: #fbf7f1;
      --line: #d8d0c8;
      --green: #0a7a52;
      --red: #b42318;
      --amber: #b7791f;
      --text: #102a34;
      --muted: #60717a;
      --white: #fff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--cream);
      color: var(--text);
      font-family: "Rubrik", Arial, sans-serif;
      letter-spacing: 0;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px;
    }}
    header {{
      background: var(--ink);
      color: var(--white);
      padding: 24px 28px;
      border-radius: 4px;
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: end;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      line-height: 1.05;
    }}
    .sub {{
      margin-top: 8px;
      color: #d9e8ed;
      font-size: 14px;
    }}
    .updated {{
      border: 1px solid rgba(255,255,255,.38);
      padding: 10px 14px;
      border-radius: 3px;
      font-weight: 600;
      white-space: nowrap;
      font-size: 13px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
      margin: 18px 0;
    }}
    .card {{
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 4px;
      overflow: hidden;
    }}
    .card span {{
      display: block;
      text-align: center;
      background: var(--orange);
      color: var(--white);
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 700;
    }}
    .card strong {{
      display: block;
      text-align: center;
      padding: 18px 10px;
      color: var(--ink);
      font-size: 30px;
      line-height: 1;
    }}
    .card:nth-child(2) span {{ background: var(--ink-2); }}
    .card:nth-child(3) span {{ background: var(--green); }}
    .card:nth-child(4) span {{ background: var(--ink); }}
    .table-wrap {{
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 4px;
      overflow: hidden;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th {{
      background: var(--ink);
      color: var(--white);
      padding: 12px 10px;
      font-size: 13px;
      text-align: right;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    td {{
      border-top: 1px solid var(--line);
      padding: 13px 10px;
      text-align: right;
      font-size: 18px;
      font-weight: 600;
    }}
    td:first-child {{
      color: var(--ink);
      font-size: 16px;
      font-weight: 700;
    }}
    tr:nth-child(even) td {{ background: #fff8f1; }}
    tr.ok td:nth-child(6) {{ color: var(--green); }}
    tr.warn td:nth-child(6) {{ color: var(--amber); }}
    tr.low td:nth-child(6) {{ color: var(--red); }}
    footer {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 12px;
      line-height: 1.45;
    }}
    @media (max-width: 820px) {{
      main {{ padding: 14px; }}
      header {{ display: block; }}
      .updated {{ display: inline-block; margin-top: 14px; }}
      .cards {{ grid-template-columns: 1fr 1fr; }}
      td {{ font-size: 14px; }}
      th {{ font-size: 11px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Painel de Metas CRM</h1>
        <div class="sub">Positivação por cliente único em janela de 180 dias</div>
      </div>
      <div class="updated">Atualizado em {safe_text(data['updated_at'])}</div>
    </header>
    <section class="cards">
      <div class="card"><span>Realizado 2025</span><strong>{format_int(totals['realizado_2025'])}</strong></div>
      <div class="card"><span>Meta 2026</span><strong>{format_int(totals['meta'])}</strong></div>
      <div class="card"><span>Realizado 2026</span><strong>{format_int(totals['realizado_2026'])}</strong></div>
      <div class="card"><span>Atingimento</span><strong>{totals['atingimento']}%</strong></div>
    </section>
    <section class="table-wrap">
      <table aria-label="Metas mensais CRM">
        <thead>
          <tr>
            <th>Mês</th>
            <th>Realizado 2025</th>
            <th>Meta</th>
            <th>Realizado 2026</th>
            <th>Taxa recompra</th>
            <th>% Meta</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </section>
    <footer>
      Dados atualizados automaticamente pela API Magazord.
    </footer>
  </main>
</body>
</html>
"""


def copy_brand_fonts(output_dir: Path) -> None:
    """Copia fontes Rubrik enviadas pelo usuário para o painel público."""
    font_source = Path("data/input/metas_bugbee_20260528")
    font_target = output_dir / "fonts"
    font_target.mkdir(parents=True, exist_ok=True)
    for filename in ("Rubrik.otf", "Rubrik SemiBold.otf", "Rubrik Bold.otf"):
        source = font_source / filename
        if source.exists():
            (font_target / filename).write_bytes(source.read_bytes())


def export_panel(data: dict, output_dir: Path) -> None:
    """Exporta HTML e JSON público do painel."""
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_brand_fonts(output_dir)
    (output_dir / "index.html").write_text(render_html(data), encoding="utf-8")
    (output_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Lê argumentos CLI."""
    parser = argparse.ArgumentParser(description="Gera painel público de metas CRM Bugbee.")
    parser.add_argument("--output", default="./docs/crm-metas", help="Pasta pública do painel.")
    parser.add_argument("--start", default="2000-01-01", help="Data inicial da API.")
    parser.add_argument("--end", default=date.today().isoformat(), help="Data final da API.")
    return parser.parse_args()


def main() -> None:
    """Executa atualização do painel."""
    args = parse_args()
    output_dir = Path(args.output).resolve()
    logger = setup_logger(Path("logs") / "painel_crm.log")
    data = build_dashboard_data(pd.Timestamp(args.start).date(), pd.Timestamp(args.end).date(), logger)
    export_panel(data, output_dir)
    print(f"Painel gerado em {output_dir}")


if __name__ == "__main__":
    main()
