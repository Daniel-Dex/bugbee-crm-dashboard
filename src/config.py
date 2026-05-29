from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # Allows `--no-api` validation before dependencies are installed.
    def load_dotenv(*args, **kwargs):
        return False


REQUIRED_ENV = ("MAGAZORD_BASE_URL", "MAGAZORD_API_KEY", "MAGAZORD_API_SECRET")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    api_secret: str
    project_root: Path
    raw_dir: Path
    processed_dir: Path
    history_dir: Path
    output_dir: Path
    template_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class Period:
    run_date: date
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    yoy_start: date
    yoy_end: date

    @property
    def label(self) -> str:
        return f"{self.current_start:%d/%m/%Y} a {self.current_end:%d/%m/%Y}"


def load_settings(project_root: Path | None = None, require_credentials: bool = True) -> Settings:
    root = project_root or Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")

    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing and require_credentials:
        names = ", ".join(missing)
        raise RuntimeError(f"Variáveis de ambiente ausentes: {names}")

    data_dir = root / "data"
    return Settings(
        base_url=(os.getenv("MAGAZORD_BASE_URL") or "").rstrip("/"),
        api_key=os.getenv("MAGAZORD_API_KEY") or "",
        api_secret=os.getenv("MAGAZORD_API_SECRET") or "",
        project_root=root,
        raw_dir=data_dir / "raw",
        processed_dir=data_dir / "processed",
        history_dir=data_dir / "history",
        output_dir=data_dir / "output",
        template_dir=data_dir / "templates",
        logs_dir=root / "logs",
    )


def compute_weekly_period(run_dt: datetime | None = None) -> Period:
    now = (run_dt or datetime.now(SAO_PAULO)).astimezone(SAO_PAULO)
    run_day = now.date()
    current_end = run_day - timedelta(days=run_day.weekday() + 1)
    current_start = current_end - timedelta(days=6)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    yoy_start = current_start.replace(year=current_start.year - 1)
    yoy_end = current_end.replace(year=current_end.year - 1)
    return Period(run_day, current_start, current_end, previous_start, previous_end, yoy_start, yoy_end)
