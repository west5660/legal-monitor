from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass
class ProfileRules:
    keywords_any: list[str] = field(default_factory=list)
    keywords_exclude: list[str] = field(default_factory=list)


@dataclass
class Profile:
    id: str
    name: str
    enabled: bool
    description: str
    rules: ProfileRules


@dataclass
class Settings:
    fetch_window_days: int
    retention_days: int
    cleanup_batch_days: int
    sources: dict[str, bool]
    relevance_threshold: float
    data_dir: Path
    downloads_dir: Path
    output_dir: Path
    duma_api_key: str
    use_playwright_sozd: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "legal_monitor.db"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = _load_yaml(CONFIG_DIR / "settings.yaml")

    data_dir = PROJECT_ROOT / raw.get("data_dir", "data")
    downloads_dir = PROJECT_ROOT / raw.get("downloads_dir", "data/downloads")
    output_dir = PROJECT_ROOT / raw.get("output_dir", "output")

    for path in (data_dir, downloads_dir, output_dir):
        path.mkdir(parents=True, exist_ok=True)

    return Settings(
        fetch_window_days=int(os.getenv("FETCH_WINDOW_DAYS", raw.get("fetch_window_days", 14))),
        retention_days=int(os.getenv("RETENTION_DAYS", raw.get("retention_days", 60))),
        cleanup_batch_days=int(os.getenv("CLEANUP_BATCH_DAYS", raw.get("cleanup_batch_days", 14))),
        sources=raw.get("sources", {}),
        relevance_threshold=float(raw.get("relevance_threshold", 0.35)),
        data_dir=data_dir,
        downloads_dir=downloads_dir,
        output_dir=output_dir,
        duma_api_key=os.getenv("DUMA_API_KEY", ""),
        use_playwright_sozd=os.getenv("USE_PLAYWRIGHT_SOZD", "false").lower() == "true",
    )


def load_profiles() -> list[Profile]:
    raw = _load_yaml(CONFIG_DIR / "profiles.yaml")
    profiles: list[Profile] = []
    for item in raw.get("profiles", []):
        rules_raw = item.get("rules", {})
        profiles.append(
            Profile(
                id=item["id"],
                name=item["name"],
                enabled=bool(item.get("enabled", True)),
                description=item.get("description", ""),
                rules=ProfileRules(
                    keywords_any=[k.lower() for k in rules_raw.get("keywords_any", [])],
                    keywords_exclude=[k.lower() for k in rules_raw.get("keywords_exclude", [])],
                ),
            )
        )
    return profiles


def save_profiles(profiles: list[Profile]) -> None:
    data = {
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "enabled": p.enabled,
                "description": p.description,
                "rules": {
                    "keywords_any": p.rules.keywords_any,
                    "keywords_exclude": p.rules.keywords_exclude,
                },
            }
            for p in profiles
        ]
    }
    path = CONFIG_DIR / "profiles.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def get_date_window(settings: Settings) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=settings.fetch_window_days), today
