from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from openai import OpenAI

    from legal_monitor.config import Settings

logger = logging.getLogger(__name__)

_gigachat_token: str = ""
_gigachat_token_expires: float = 0.0
_ollama_resolved_model: str | None = None

OLLAMA_FALLBACK_MODELS = ("qwen2.5:7b", "qwen2.5:3b", "llama3.2:3b")


def create_llm_client(settings: Settings) -> OpenAI:
    from openai import OpenAI

    if settings.llm_provider == "gigachat":
        token = _get_gigachat_access_token(settings.llm_api_key, settings.llm_scope)
        return OpenAI(api_key=token, base_url=settings.llm_base_url, timeout=120.0)

    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=120.0)


def ensure_ollama_model(settings: Settings) -> str:
    """Проверить, что модель Ollama установлена; при необходимости скачать."""
    global _ollama_resolved_model

    if _ollama_resolved_model:
        return _ollama_resolved_model

    api_root = _ollama_api_root(settings.llm_base_url)
    preferred = settings.llm_model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    installed = _list_ollama_models(api_root)

    if installed:
        resolved = _pick_model(preferred, installed)
        if resolved != preferred:
            logger.warning(
                "Ollama: модель '%s' не найдена, используется '%s'. "
                "Установленные: %s",
                preferred,
                resolved,
                ", ".join(installed),
            )
        else:
            logger.info("Ollama: модель '%s' готова", resolved)
        _ollama_resolved_model = resolved
        return resolved

    candidates = [preferred, *OLLAMA_FALLBACK_MODELS]
    seen: set[str] = set()
    for model in candidates:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            _pull_ollama_model(api_root, model)
            _ollama_resolved_model = model
            logger.info("Ollama: модель '%s' успешно скачана", model)
            return model
        except Exception as exc:
            logger.warning("Ollama: не удалось скачать '%s': %s", model, exc)

    raise RuntimeError(
        "Ollama запущена, но нет ни одной модели. "
        "Выполните в терминале: ollama pull qwen2.5:7b "
        "или запустите: legal-monitor ollama-setup"
    )


def _ollama_api_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


def _list_ollama_models(api_root: str) -> list[str]:
    try:
        response = httpx.get(f"{api_root}/api/tags", timeout=10.0)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"Ollama не отвечает на {api_root}. Запустите приложение Ollama. ({exc})"
        ) from exc

    payload = response.json()
    return [item["name"] for item in payload.get("models", []) if item.get("name")]


def _pick_model(preferred: str, installed: list[str]) -> str:
    if preferred in installed:
        return preferred
    pref_base = preferred.split(":")[0]
    for name in installed:
        if name == pref_base or name.startswith(f"{pref_base}:"):
            return name
    return installed[0]


def _pull_ollama_model(api_root: str, model: str) -> None:
    logger.info("Ollama: скачивание модели %s (может занять 5–15 минут)...", model)
    last_status = ""
    with httpx.stream(
        "POST",
        f"{api_root}/api/pull",
        json={"name": model, "stream": True},
        timeout=httpx.Timeout(3600.0, connect=30.0),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            status = data.get("status", "")
            total = data.get("total") or 0
            completed = data.get("completed") or 0
            if total and completed:
                pct = 100 * completed / total
                msg = f"{status} — {pct:.0f}%"
            else:
                msg = status
            if msg and msg != last_status:
                logger.info("Ollama: %s", msg)
                last_status = msg
            if data.get("error"):
                raise RuntimeError(data["error"])


def _get_gigachat_access_token(credentials: str, scope: str) -> str:
    global _gigachat_token, _gigachat_token_expires

    if not credentials:
        raise ValueError("GIGACHAT_CREDENTIALS не задан в .env")

    now = time.time()
    if _gigachat_token and now < _gigachat_token_expires - 60:
        return _gigachat_token

    # По умолчанию проверка TLS ВКЛЮЧЕНА. GigaChat использует цепочку
    # сертификатов НУЦ Минцифры, которая часто отсутствует в системном
    # хранилище — в этом случае verify=True сразу покажет понятную ошибку,
    # и пользователь один раз установит корневой сертификат Минцифры
    # (https://www.gosuslugi.ru/crt), а не будет молча работать без TLS.
    verify_ssl = os.getenv("GIGACHAT_VERIFY_SSL", "true").lower() == "true"
    if not verify_ssl:
        logger.warning(
            "GigaChat: проверка TLS-сертификата ОТКЛЮЧЕНА (GIGACHAT_VERIFY_SSL=false). "
            "Используйте это только временно для диагностики."
        )
    response = httpx.post(
        os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"),
        headers={
            "Authorization": f"Bearer {credentials}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"scope": scope},
        timeout=60.0,
        verify=verify_ssl,
    )
    response.raise_for_status()
    payload = response.json()
    _gigachat_token = payload["access_token"]
    _gigachat_token_expires = now + float(payload.get("expires_in", 1800))
    logger.info("GigaChat: получен токен доступа")
    return _gigachat_token
