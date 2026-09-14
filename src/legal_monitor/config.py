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
    llm_min_score: float
    llm_max_documents: int
    llm_text_limit: int
    llm_all_shortlist: bool
    export_analyze_before: bool
    data_dir: Path
    downloads_dir: Path
    output_dir: Path
    duma_api_key: str
    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_scope: str
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
        llm_min_score=float(raw.get("llm_min_score", 0.35)),
        llm_max_documents=int(os.getenv("LLM_MAX_DOCUMENTS", raw.get("llm_max_documents", 0))),
        llm_text_limit=int(os.getenv("LLM_TEXT_LIMIT", raw.get("llm_text_limit", 8000))),
        llm_all_shortlist=bool(raw.get("llm_all_shortlist", True)),
        export_analyze_before=bool(raw.get("export_analyze_before", True)),
        data_dir=data_dir,
        downloads_dir=downloads_dir,
        output_dir=output_dir,
        duma_api_key=os.getenv("DUMA_API_KEY", ""),
        **_load_llm_settings(),
        use_playwright_sozd=os.getenv("USE_PLAYWRIGHT_SOZD", "false").lower() == "true",
    )


def _load_llm_settings() -> dict[str, str]:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    yandex_folder = os.getenv("YANDEX_FOLDER_ID", "").strip()
    yandex_model = os.getenv(
        "YANDEX_MODEL",
        f"gpt://{yandex_folder}/yandexgpt/latest" if yandex_folder else "yandexgpt/latest",
    )

    presets: dict[str, dict[str, str]] = {
        # Локально, 100% доступно в РФ, бесплатно без лимитов
        "ollama": {
            "llm_provider": "ollama",
            "llm_api_key": os.getenv("OLLAMA_API_KEY", "ollama").strip() or "ollama",
            "llm_base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:7b")),
            "llm_scope": "",
        },
        # Сбер, бесплатно ~900k токенов/год для физлиц, работает в РФ
        "gigachat": {
            "llm_provider": "gigachat",
            "llm_api_key": os.getenv("GIGACHAT_CREDENTIALS", "").strip(),
            "llm_base_url": os.getenv(
                "LLM_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1"
            ),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("GIGACHAT_MODEL", "GigaChat")),
            "llm_scope": os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
        },
        # Яндекс Cloud, платный (есть стартовый грант ~4000₽), работает в РФ
        "yandex": {
            "llm_provider": "yandex",
            "llm_api_key": os.getenv("YANDEX_API_KEY", "").strip(),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://ai.api.cloud.yandex.net/v1"),
            "llm_model": os.getenv("LLM_MODEL", yandex_model),
            "llm_scope": "",
        },
        "deepseek": {
            "llm_provider": "deepseek",
            "llm_api_key": os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip(),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat")),
            "llm_scope": "",
        },
        "openai": {
            "llm_provider": "openai",
            "llm_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
            "llm_scope": "",
        },
        # Зарубежные — могут быть недоступны из РФ без VPN
        "groq": {
            "llm_provider": "groq",
            "llm_api_key": os.getenv("GROQ_API_KEY", "").strip(),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
            "llm_scope": "",
        },
        "gemini": {
            "llm_provider": "gemini",
            "llm_api_key": os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")).strip(),
            "llm_base_url": os.getenv(
                "LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            "llm_model": os.getenv("LLM_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash")),
            "llm_scope": "",
        },
        "openrouter": {
            "llm_provider": "openrouter",
            "llm_api_key": os.getenv("OPENROUTER_API_KEY", "").strip(),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            "llm_model": os.getenv(
                "LLM_MODEL",
                os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free"),
            ),
            "llm_scope": "",
        },
    }

    if provider in presets:
        return presets[provider]

    return {
        "llm_provider": provider,
        "llm_api_key": os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip(),
        "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "llm_scope": "",
    }


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
