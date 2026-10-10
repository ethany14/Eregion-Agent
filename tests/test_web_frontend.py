from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from fastapi.testclient import TestClient

from api.main import create_app


def test_web_app_route_and_assets_are_served() -> None:
    with TestClient(create_app(run_service=object())) as client:
        response = client.get("/apply")
        assert response.status_code == 200
        assert "Eregion · Career agent" in response.text
        assert 'href="/app#' not in response.text
        assert 'data-view-panel=' not in response.text
        assert client.get("/web-assets/apply.css").status_code == 200
        assert client.get("/web-assets/apply.js").status_code == 200
        assert client.get("/web-assets/career-chat.js").status_code == 200
        assert response.headers["cache-control"] == "no-store"
        for path in ("/", "/app", "/app/", "/index.html", "/web-assets/index.html",
                     "/web-assets/INDEX.HTML", "/web-assets/apply.html"):
            redirect = client.get(path, follow_redirects=False)
            assert redirect.status_code == 307, path
            assert redirect.headers["location"] == "/apply"
            assert redirect.headers["cache-control"] == "no-store"
            assert client.get(path).text == response.text


def test_old_bookmarks_preserve_job_context_and_drop_old_view_settings() -> None:
    with TestClient(create_app(run_service=object())) as client:
        for path in ("/app", "/web-assets/index.html"):
            response = client.get(path, params={"application":"saved-job", "url":"https://example.org/jobs?a=1&b=2",
                                               "mode":"legacy", "next":"https://example.org"}, follow_redirects=False)
            target = urlsplit(response.headers["location"])
            assert target.path == "/apply" and not target.netloc
            assert parse_qs(target.query) == {"application":["saved-job"], "url":["https://example.org/jobs?a=1&b=2"]}



class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" and attrs.get("rel") == "stylesheet" else None
        if url and url.startswith("/web-assets/"):
            self.urls.append(url)


def test_current_chat_asset_graph_is_served_without_retired_dependencies():
    # Follow the real HTML and JS imports, including lazy-loaded workspace pages.
    with TestClient(create_app(run_service=object())) as client:
        links = AssetLinks()
        links.feed(client.get("/apply").text)
        pending, seen = links.urls[:], set()
        assert pending
        while pending:
            url = pending.pop()
            if url in seen:
                continue
            seen.add(url)
            response = client.get(url)
            assert response.status_code == 200, url
            if urlsplit(url).path.endswith(".js"):
                assert "javascript" in response.headers["content-type"]
                for specifier in re.findall(r"(?:from\s*|import\s*\(\s*|import\s+)[\"']([^\"']+)[\"']", response.text):
                    if specifier.startswith("."):
                        pending.append(urljoin(url, specifier))
        assert "/web-assets/career-chat.js" in seen
        assert "/web-assets/insights.js" in seen
        for name in ("app.js", "api.js", "styles.css", "apply-chat.css"):
            assert client.get(f"/web-assets/{name}").status_code == 404
