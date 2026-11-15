import tarfile

import httpx

from contracts import Settings
from scripts.package_release import SHOWCASE_FILES, package
from server.app import create_app


async def test_dashboard_links_to_demo_and_demo_serves_local_assets(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as client:
        assert 'href="/demo"' in (await client.get("/")).text
        redirect = await client.get("/demo")
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "/demo/"
        page = await client.get("/demo/")
        assert page.status_code == 200
        assert 'id="intro-title"' in page.text
        assert 'data-slide="intro"' not in page.text
        for asset in SHOWCASE_FILES:
            response = await client.get(f"/demo/{asset}")
            assert response.status_code == 200, asset
        assert (await client.get("/showcase/")).status_code == 200


def test_release_contains_only_selected_showcase_assets(tmp_path):
    archive_path = tmp_path / "release.tar.gz"
    package(archive_path)
    with tarfile.open(archive_path) as archive:
        names = set(archive.getnames())
    assert {name for name in names if name.startswith("web/showcase/")} == {
        "web/showcase/" + name for name in SHOWCASE_FILES
    }
