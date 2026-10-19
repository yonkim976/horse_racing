"""Run with unittest in a network-isolated, read-only release container."""

import unittest
from urllib.robotparser import RobotFileParser

from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from horse_racing.web.app import create_app
from horse_racing.web.crawler_policy import scanner_probe_reason


def forbidden_database():
    raise AssertionError("Crawler protection fixtures must not open a database")


def route_client(calls):
    app = create_app(session_factory=forbidden_database)
    app.router.routes.clear()

    def normal_route():
        calls.append(True)
        return PlainTextResponse("normal page")

    app.add_api_route("/{path:path}", normal_route, methods=["GET", "HEAD", "POST"])
    return TestClient(app)


class CrawlerProtectionTests(unittest.TestCase):
    def test_amazon_is_denied_before_route_for_each_method(self):
        for ua in ("Amazonbot/0.1", "amazonBOT", "Mozilla/5.0 (compatible; Amazonbot/0.1)"):
            for method in ("GET", "HEAD", "POST"):
                with self.subTest(ua=ua, method=method):
                    calls = []
                    with route_client(calls) as client:
                        response = client.request(
                            method, "/races/55172", headers={"User-Agent": ua},
                        )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.content, b"")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertEqual(calls, [])

    def test_normal_search_bots_and_humans_are_not_newly_blocked(self):
        for ua in ("Googlebot/2.1", "Googlebot-Image/1.0", "Yeti/1.1 (+https://naver.me/spd)",
                   "Mozilla/5.0 Chrome/128 Safari/537.36", "Amzn-SearchBot/0.1", "Amzn-User/0.1"):
            with self.subTest(ua=ua):
                calls = []
                with route_client(calls) as client:
                    for path in ("/", "/races/55172", "/horses/0061533",
                                 "/static/css/dashboard.css"):
                        response = client.get(path, headers={"User-Agent": ua})
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn("noindex", response.headers.get("x-robots-tag", ""))
                self.assertEqual(len(calls), 4)

    def test_scanner_paths_are_empty_404_without_route_or_database(self):
        paths = ("/.env", "/mailjet/.env", "/.ENV.production", "/.env.backup",
                 "/.git/config", "/nested/.svn/entries", "/.hg/store", "/php.php",
                 "/admin/phpinfo.php", "/wp-admin/install.php", "/wp-login.php",
                 "/wp-content/uploads/test", "/WP-INCLUDES/version", "/phpmyadmin/index.php",
                 "/shell.php/anything", "/shell.phtml", "/shell.phar", "/%2eenv",
                 "/%252eenv", "/%2egit/config", "/?rest_route=/wp/v2/users")
        for path in paths:
            for method in ("GET", "HEAD", "POST"):
                with self.subTest(path=path, method=method):
                    calls = []
                    with route_client(calls) as client:
                        response = client.request(method, path)
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.content, b"")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertEqual(calls, [])

    def test_search_agent_does_not_bypass_probe_guard(self):
        for ua in ("Googlebot/2.1", "Yeti/1.1"):
            calls = []
            with route_client(calls) as client:
                response = client.get("/.git/config", headers={"User-Agent": ua})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(calls, [])

    def test_public_files_and_ordinary_queries_are_not_scanner_paths(self):
        paths = ("/robots.txt", "/sitemap.xml", "/sitemap-index.xml", "/sitemap-races.xml",
                 "/.well-known/acme-challenge/test", "/analysis?tab=records&horse=1",
                 "/horses?q=wp-admin", "/horses?q=php", "/static/images/.environment.svg",
                 "/static/css/phpmyadmin.css", "/health", "/health/ready")
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNone(scanner_probe_reason(path.split("?", 1)[0]))
                calls = []
                with route_client(calls) as client:
                    response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(calls, [True])

    def test_invalid_query_keeps_existing_validation_not_probe_denial(self):
        calls = []
        with route_client(calls) as client:
            response = client.get("/analysis?tab=records&horse=php")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(calls, [])

    def test_robots_and_sitemap_preserve_search_access(self):
        app = create_app(session_factory=forbidden_database)
        with TestClient(app) as client:
            for ua in ("Amazonbot/0.1", "Googlebot/2.1", "Yeti/1.1"):
                robots = client.get("/robots.txt", headers={"User-Agent": ua})
                self.assertEqual(robots.status_code, 200)
            sitemap = client.get("/sitemap.xml", headers={"User-Agent": "Googlebot/2.1"})
        policy = RobotFileParser()
        policy.parse(robots.text.splitlines())
        self.assertFalse(policy.can_fetch("Amazonbot", "https://mapilog.xyz/"))
        for agent in ("Googlebot", "Googlebot-Image", "Yeti"):
            for path in ("/", "/races/55172", "/horses/0061533", "/static/css/dashboard.css"):
                self.assertTrue(policy.can_fetch(agent, "https://mapilog.xyz" + path))
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("xml", sitemap.headers["content-type"])
        self.assertIn("https://mapilog.xyz/", sitemap.text)


if __name__ == "__main__":
    unittest.main()
