"""Bounded, primary-key range scans for public detail sitemaps."""

from urllib.parse import quote
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.db.models import Race, Racecourse, RunningTrial
from horse_racing.web.entities import ENTITY_KINDS
from horse_racing.web.race_scope import active_race_clause
from horse_racing.web.seo import PUBLIC_SITE_ORIGIN

PARTITION_SIZE = 1000
MAX_PARTITION = 9999
DETAIL_MODELS = {
    "races": Race,
    "running-trials": RunningTrial,
    **{slug: kind.model for slug, kind in ENTITY_KINDS.items()},
}


def xml_document(paths: list[str], *, index: bool = False) -> bytes:
    root = ElementTree.Element(
        "sitemapindex" if index else "urlset",
        xmlns="http://www.sitemaps.org/schemas/sitemap/0.9",
    )
    for path in paths:
        item = ElementTree.SubElement(root, "sitemap" if index else "url")
        ElementTree.SubElement(item, "loc").text = PUBLIC_SITE_ORIGIN + path
    # No synthetic lastmod: race/entity tables have no reliable timestamp for
    # all changes to their rendered content (results, histories and profiles).
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def load_sitemap_index(session: Session) -> bytes:
    paths = ["/sitemap.xml", "/sitemaps/distances.xml"]
    for slug, model in DETAIL_MODELS.items():
        maximum = session.scalar(select(model.id).order_by(model.id.desc()).limit(1)) or 0
        partitions = (maximum + PARTITION_SIZE - 1) // PARTITION_SIZE
        if partitions > MAX_PARTITION + 1:
            raise ValueError("sitemap partition capacity exceeded")
        paths.extend(f"/sitemaps/{slug}/{part}.xml" for part in range(partitions))
    return xml_document(paths, index=True)


def load_detail_sitemap(session: Session, slug: str, partition: int) -> bytes:
    model = DETAIL_MODELS[slug]
    lower = partition * PARTITION_SIZE
    statement = select(model.id).where(model.id > lower, model.id <= lower + PARTITION_SIZE)
    if slug == "races":
        statement = statement.join(Racecourse).where(active_race_clause())
    if slug in ENTITY_KINDS:
        official_id = getattr(model, ENTITY_KINDS[slug].id_attr)
        statement = statement.with_only_columns(official_id)
    rows = session.scalars(statement.order_by(model.id).limit(PARTITION_SIZE))
    return xml_document([f"/{slug}/{quote(str(value), safe='')}" for value in rows])


def load_distance_sitemap(session: Session) -> bytes:
    # Match the latest completed season chosen by the page loader, including
    # courses without current-year races. Never publish empty historic filters.
    courses = {1: "seoul", 2: "jeju", 3: "busan", 4: "yeongcheon"}
    paths = []
    for meet, course in courses.items():
        conditions = [
            Race.status == "completed", active_race_clause(), Racecourse.kra_meet_code == meet,
        ]
        latest = session.scalar(
            select(Race.race_date_local).join(Racecourse).where(*conditions)
            .order_by(Race.race_date_local.desc()).limit(1)
        )
        if latest is None:
            continue
        distances = session.scalars(
            select(Race.distance_m).join(Racecourse).where(
                *conditions,
                Race.race_date_local >= latest.replace(month=1, day=1),
                Race.race_date_local <= latest.replace(month=12, day=31),
                Race.distance_m.between(800, 4000),
            ).distinct().order_by(Race.distance_m)
        )
        paths.extend(f"/racecourses/{course}/distances/{distance}" for distance in distances)
    return xml_document(paths)
