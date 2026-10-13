import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_dashboard import seeded_session

from horse_racing.db.models import Horse, Race, Racecourse
from horse_racing.web.app import create_app
from horse_racing.web.sitemaps import PARTITION_SIZE, load_detail_sitemap

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@pytest.fixture
def factory(tmp_path: Path):
    return seeded_session(tmp_path)


def locations(body: bytes, *, index: bool = False) -> list[str]:
    root = ElementTree.fromstring(body)
    return [item.text for item in root.findall(
        "s:sitemap/s:loc" if index else "s:url/s:loc", NS,
    )]


@pytest.mark.parametrize("headers", [{}, {"user-agent": "Mozilla/5.0 iPhone"}])
def test_tracking_variants_and_unknown_queries_do_not_contaminate_seo_cache(factory, headers):
    with TestClient(create_app(session_factory=factory)) as client:
        for query, expected in [
            ("?noise=one", "noindex,follow"),
            ("?utm_source=chatgpt.com", "index,follow"),
            ("?utm_source=another", "index,follow"),
            ("", "index,follow"),
            ("?noise=two", "noindex,follow"),
            ("?date=2026-08-21", "noindex,follow"),
        ]:
            response = client.get("/" + query, headers=headers)
            assert response.status_code == 200
            soup = BeautifulSoup(response.text, "html.parser")
            assert soup.find("meta", attrs={"name": "robots"})["content"] == expected
            assert soup.find("link", rel="canonical")["href"] == "https://mapilog.xyz/"
            graph = json.loads(soup.find("script", type="application/ld+json").string)
            assert graph["@graph"][1]["url"] == "https://mapilog.xyz/"


def test_distance_landing_redirect_and_filtered_variants(factory):
    with TestClient(create_app(session_factory=factory)) as client:
        legacy = client.get("/racecourses/jeju/distances?distance=900", follow_redirects=False)
        assert legacy.status_code == 301
        assert legacy.headers["location"] == "/racecourses/jeju/distances/900"
        response = client.get(legacy.headers["location"])
        soup = BeautifulSoup(response.text, "html.parser")
        assert response.status_code == 200
        assert soup.find("meta", attrs={"name": "robots"})["content"] == "index,follow"
        assert soup.find("link", rel="canonical")["href"].endswith("/distances/900")
        assert "900m" in soup.title.text
        assert "정상 완주 기록" in response.text
        assert 'href="/racecourses/jeju/distances/900"' in response.text
        filtered = client.get("/racecourses/jeju/distances/900?year=2026&grade=제6등급")
        assert filtered.status_code == 200
        assert 'content="noindex,follow"' in filtered.text
        assert client.get("/racecourses/jeju/distances/999").status_code == 404
        assert client.get("/racecourses/jeju/distances/900?page=201").status_code == 422
        padded = client.get("/racecourses/jeju/distances/0900", follow_redirects=False)
        assert padded.headers["location"] == "/racecourses/jeju/distances/900"


def test_sitemaps_cover_details_and_only_populated_distance_landings(factory):
    with TestClient(create_app(session_factory=factory)) as client:
        robots = client.get("/robots.txt")
        assert "Sitemap: https://mapilog.xyz/sitemap-index.xml" in robots.text
        index = client.get("/sitemap-index.xml")
        assert index.status_code == 200
        urls = locations(index.content, index=True)
        assert "https://mapilog.xyz/sitemap.xml" in urls
        for slug, expected in [
            ("races", "/races/1"), ("running-trials", "/running-trials/1"),
            ("horses", "/horses/003001"), ("jockeys", "/jockeys/080101"),
            ("trainers", "/trainers/070101"), ("owners", "/owners/050101"),
        ]:
            path = f"/sitemaps/{slug}/0.xml"
            assert "https://mapilog.xyz" + path in urls
            response = client.get(path)
            assert response.status_code == 200
            assert "https://mapilog.xyz" + expected in locations(response.content)
            assert b"lastmod" not in response.content
        distances = client.get("/sitemaps/distances.xml")
        assert "https://mapilog.xyz/racecourses/jeju/distances/900" in locations(
            distances.content,
        )
        for url in locations(distances.content):
            assert client.get(url).status_code == 200


def test_sitemap_partition_boundaries_escaping_and_retired_races(factory):
    with factory() as session:
        session.add_all([
            Horse(id=PARTITION_SIZE, kra_horse_id="edge&horse", name_ko="경계"),
            Horse(id=PARTITION_SIZE + 1, kra_horse_id="next", name_ko="다음"),
        ])
        course = session.scalar(select(Racecourse).where(Racecourse.kra_meet_code == 2))
        original = session.get(Race, 1)
        session.add(Race(
            racecourse=course, race_date_local=original.race_date_local,
            race_number=99, distance_m=900, grade="한OPEN", status="completed",
        ))
        session.flush()
        retired_id = session.scalar(select(Race.id).where(Race.grade == "한OPEN"))
        first = locations(load_detail_sitemap(session, "horses", 0))
        second = locations(load_detail_sitemap(session, "horses", 1))
        assert "https://mapilog.xyz/horses/edge%26horse" in first
        assert "https://mapilog.xyz/horses/next" in second
        assert not set(first) & set(second)
        assert f"https://mapilog.xyz/races/{retired_id}" not in locations(
            load_detail_sitemap(session, "races", 0),
        )


def test_invalid_sitemaps_are_rejected_before_database_access():
    def unavailable_session():
        raise AssertionError("invalid sitemap must not open a database session")

    with TestClient(create_app(session_factory=unavailable_session)) as client:
        assert client.get("/sitemaps/secrets/0.xml").status_code == 404
        assert client.get("/sitemaps/horses/10000.xml").status_code == 422
        assert client.get("/sitemaps/horses/-1.xml").status_code == 422


@pytest.mark.parametrize("agent", ["Claude-SearchBot/1.0", "Claude-User/1.0", "OAI-SearchBot"])
def test_search_bots_can_retrieve_public_guide(agent):
    with TestClient(create_app()) as client:
        response = client.get("/guide", headers={"user-agent": agent})
        assert response.status_code == 200


@pytest.mark.parametrize("path", ["/horses/003001", "/jockeys/080101"])
def test_recent_records_are_linked_from_canonical_entity_page(factory, path):
    with TestClient(create_app(session_factory=factory)) as client:
        soup = BeautifulSoup(client.get(path).text, "html.parser")
        summary = soup.find("section", attrs={"aria-label": "최근 출전 요약"})
        assert summary.find("a", href="/races/1")
        assert len(summary.find_all("li")) <= 5


def test_jsonld_escapes_names_and_privacy_stays_noindex(factory):
    with factory() as session:
        session.get(Horse, 1).name_ko = '</script><script>alert("name")</script>'
        session.commit()
    with TestClient(create_app(session_factory=factory)) as client:
        response = client.get("/horses/003001")
        soup = BeautifulSoup(response.text, "html.parser")
        graph = json.loads(soup.find("script", type="application/ld+json").string)
        assert '</script>' in graph["@graph"][1]["name"]
        assert '<script>alert("name")</script>' not in response.text
        privacy = client.get("/privacy?utm_source=example")
        assert 'content="noindex,follow"' in privacy.text
