from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import compute_weekly_period, load_settings
from src.logs import setup_logger
from src.magazord_client import MagazordClient


settings = load_settings()
period = compute_weekly_period()
logger = setup_logger(Path("logs/probe_nota_fiscal_detail.txt"))
client = MagazordClient(settings.base_url, settings.api_key, settings.api_secret, logger)
result = client.get_paginated(
    "nf",
    "/v2/faturamento/notaFiscal",
    {"date": period.current_start.isoformat(), "date_end": period.current_end.isoformat(), "tipo": 1},
    limit=1,
)
nf = result.rows[0]
print("nf id", nf.get("id"))
payload = client._request("GET", f"/v2/faturamento/notaFiscal/{nf.get('id')}")
obj = payload.get("data", payload) if isinstance(payload, dict) else payload
if isinstance(obj, dict) and "items" in obj and isinstance(obj["items"], list) and obj["items"]:
    obj = obj["items"][0]
print("keys", sorted(obj.keys()) if isinstance(obj, dict) else type(obj).__name__)
print("item_keys", sorted(obj.get("itens", [{}])[0].keys()) if isinstance(obj, dict) and obj.get("itens") else [])
