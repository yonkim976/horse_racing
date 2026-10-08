"""Sitemap index and bounded sitemap sections for public detail pages."""

from __future__ import annotations

import re
from math import ceil
from urllib.parse import quote
from xml.sax.saxutils import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import Race
from horse_racing.web.entities import ENTITY_KINDS

# Keeps each section well under the 2 MiB response ceiling (~60 bytes per URL).
SECTION_SIZE = 10_000
_SECTION_NAME = re.compile(r"(races|horses|jockeys|trainers|owners)-([1-9][0-9]{0,4})")
_XMLNS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _section_count(session: Session, kind: str) -> int:
    if kind == "races":
        total = session.scalar(select(func.count(Race.id))) or 0
    else:
        entity = ENTITY_KINDS[kind]
        column = getattr(entity.model, entity.id_attr)
        total = session.scalar(select(func.count()).where(column.is_not(None))) or 0
    return ceil(total / SECTION_SIZE)


def sitemap_index(session: Session, origin: str) -> str:
    names = ["pages"]
    for kind in ("races", *ENTITY_KINDS):
        names.extend(f"{kind}-{page}" for page in range(1, _section_count(session, kind) + 1))
    body = "\n".join(
        f"  <sitemap><loc>{escape(f'{origin}/sitemaps/{name}.xml')}</loc></sitemap>"
        for name in names
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<sitemapindex xmlns="{_XMLNS}">\n{body}\n</sitemapindex>\n'
    )


def _section_paths(session: Session, kind: str, page: int) -> list[str]:
    offset = (page - 1) * SECTION_SIZE
    if kind == "races":
        ids = session.scalars(
            select(Race.id).order_by(Race.id).offset(offset).limit(SECTION_SIZE)
        )
        return [f"/races/{race_id}" for race_id in ids]
    entity = ENTITY_KINDS[kind]
    column = getattr(entity.model, entity.id_attr)
    official_ids = session.scalars(
        select(column)
        .where(column.is_not(None))
        .order_by(column)
        .offset(offset)
        .limit(SECTION_SIZE)
    )
    return [f"/{kind}/{quote(official_id, safe='')}" for official_id in official_ids]


def sitemap_section(
    session: Session, name: str, origin: str, static_paths: tuple[str, ...]
) -> str | None:
    """Return a urlset document, or None when the section does not exist."""
    if name == "pages":
        paths = list(static_paths)
    else:
        match = _SECTION_NAME.fullmatch(name)
        if match is None:
            return None
        paths = _section_paths(session, match.group(1), int(match.group(2)))
        if not paths:
            return None
    body = "\n".join(f"  <url><loc>{escape(origin + path)}</loc></url>" for path in paths)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="{_XMLNS}">\n{body}\n</urlset>\n'
    )
