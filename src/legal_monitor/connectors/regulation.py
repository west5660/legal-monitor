from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from legal_monitor.connectors.base import BaseConnector
from legal_monitor.models import RawDocument

logger = logging.getLogger(__name__)

API_URL = "https://regulation.gov.ru/api/npalist"


class RegulationConnector(BaseConnector):
    name = "regulation"

    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        documents: list[RawDocument] = []
        offset = 0
        limit = 100
        headers = {"User-Agent": "LegalMonitor/0.1", "Accept": "application/json, application/xml"}

        with httpx.Client(timeout=60.0, headers=headers, follow_redirects=True) as client:
            while True:
                params = {"limit": limit, "offset": offset, "sort": "desc"}
                try:
                    response = client.get(API_URL, params=params)
                    response.raise_for_status()
                    items = _parse_response(response)
                except Exception as exc:
                    logger.warning("regulation.gov.ru: %s", exc)
                    break

                if not items:
                    break

                stop = False
                for item in items:
                    pub_date = _parse_date(
                        item.get("PublishDate") or item.get("Date") or item.get("date")
                    )
                    if pub_date and pub_date < date_from:
                        stop = True
                        break
                    if pub_date and pub_date > date_to:
                        continue

                    project_id = str(
                        item.get("IDProject")
                        or item.get("projectId")
                        or item.get("id")
                        or ""
                    )
                    title = item.get("Title") or item.get("title") or ""
                    if not project_id or not title:
                        continue

                    stage = str(item.get("Stage") or item.get("stage") or "")
                    department = str(
                        item.get("CreatorDepartment") or item.get("department") or ""
                    )
                    # XML npalist: <department id="8">Минфин</department>
                    procedure = str(item.get("procedure") or "")
                    body_parts = [title.strip()]
                    if stage:
                        body_parts.append(f"Стадия: {stage}")
                    if department:
                        body_parts.append(f"Ведомство: {department}")
                    if procedure:
                        body_parts.append(f"Процедура: {procedure}")
                    rationale = str(item.get("rationale") or item.get("problem") or "")
                    if rationale:
                        body_parts.append(rationale)

                    documents.append(
                        RawDocument(
                            source="regulation",
                            external_id=project_id,
                            title=title.strip(),
                            doc_type=str(item.get("Kind") or item.get("kind") or "Проект НПА"),
                            register_date=pub_date,
                            stage=stage,
                            url=f"https://regulation.gov.ru/projects/{project_id}",
                            initiator=department,
                            text="\n\n".join(body_parts),
                        )
                    )

                if stop or len(items) < limit:
                    break
                offset += limit

        logger.info("regulation.gov.ru: получено %s проектов", len(documents))
        return documents


def _parse_response(response: httpx.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "")
    text = response.text.strip()
    if "json" in content_type or text.startswith("{") or text.startswith("["):
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "projects"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    root = ElementTree.fromstring(text)
    items: list[dict[str, Any]] = []
    for node in root.iter():
        if not (node.tag.endswith("item") or node.tag.endswith("project")):
            continue
        item: dict[str, Any] = {}
        if node.attrib.get("id"):
            item["id"] = node.attrib["id"]
        for child in node:
            tag = child.tag.split("}")[-1]
            item[tag] = (child.text or "").strip()
            if child.attrib.get("id") and tag in ("stage", "status"):
                item[f"{tag}Id"] = child.attrib["id"]
        if item:
            items.append(item)
    return items


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None
