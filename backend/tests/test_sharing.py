import pytest

from tests.conftest import login


@pytest.fixture
def two_users(admin):
    """admin owns two items with private details; bob is another user."""
    snes = next(p["id"] for p in admin.get("/api/platforms").json() if p["slug"] == "snes")
    for title, fields in (
        (
            "Super Metroid",
            {
                "purchase_price": "40",
                "purchase_date": "2020-01-01",
                "notes": "secret stash",
                "location": "Safe",
            },
        ),
        ("Wanted Game", {"status": "wishlist", "target_price": "15", "tags": ["grail"]}),
    ):
        product = admin.post("/api/products", json={"title": title, "platform_id": snes}).json()
        admin.post("/api/collection", json={"product_id": product["id"], **fields})
    admin.post("/api/users", json={"username": "bob", "password": "password123"})
    admin_id = admin.get("/api/auth/me").json()["id"]
    return admin, admin_id


def _as_bob(client):
    login(client, "bob")


def test_private_by_default(two_users):
    client, admin_id = two_users
    assert client.get("/api/auth/sharing").json() == {"share_collection": False, "share_paid": False}
    _as_bob(client)
    assert client.get("/api/shared").json() == []
    for path in ("collection", "facets", "summary"):
        assert client.get(f"/api/shared/{admin_id}/{path}").status_code == 404
    # nonexistent user looks the same as a private one
    assert client.get("/api/shared/9999/collection").status_code == 404


def test_shared_hides_notes_location_and_paid(two_users):
    client, admin_id = two_users
    client.put("/api/auth/sharing", json={"share_collection": True, "share_paid": False})
    _as_bob(client)

    sharers = client.get("/api/shared").json()
    assert [(s["username"], s["items"], s["shows_paid"]) for s in sharers] == [("admin", 1, False)]

    page = client.get(f"/api/shared/{admin_id}/collection").json()
    assert page["owner"] == "admin" and page["total"] == 2 and page["shows_paid"] is False
    for item in page["items"]:
        for field in ("notes", "location", "purchase_price", "purchase_date", "target_price", "sold_price"):
            assert item[field] is None, field
    wanted = next(i for i in page["items"] if i["product"]["title"] == "Wanted Game")
    assert wanted["tags"] == ["grail"] and wanted["status"] == "wishlist"

    # Search can't be used to probe private notes
    assert client.get(f"/api/shared/{admin_id}/collection", params={"q": "secret"}).json()["total"] == 0
    assert client.get(f"/api/shared/{admin_id}/collection", params={"q": "metroid"}).json()["total"] == 1
    # ...nor location filters, nor sorting by hidden prices
    assert client.get(f"/api/shared/{admin_id}/collection", params={"location": "Safe"}).json()["total"] == 2
    assert client.get(f"/api/shared/{admin_id}/facets").json()["locations"] == []
    assert "cost_basis" not in client.get(f"/api/shared/{admin_id}/summary").json()


def test_share_paid(two_users):
    client, admin_id = two_users
    client.put("/api/auth/sharing", json={"share_collection": True, "share_paid": True})
    _as_bob(client)
    page = client.get(f"/api/shared/{admin_id}/collection", params={"status": "owned"}).json()
    item = page["items"][0]
    assert page["shows_paid"] and item["purchase_price"] == "40.00" and item["purchase_date"] == "2020-01-01"
    assert item["notes"] is None and item["location"] is None  # never shared
    assert client.get(f"/api/shared/{admin_id}/summary").json()["cost_basis"] == 40.0


def test_share_paid_requires_sharing_and_viewer_is_read_only(two_users):
    client, admin_id = two_users
    assert client.put("/api/auth/sharing", json={"share_collection": False, "share_paid": True}).json() == {
        "share_collection": False,
        "share_paid": False,
    }
    client.put("/api/auth/sharing", json={"share_collection": True})
    item_id = client.get("/api/collection").json()["items"][0]["id"]
    _as_bob(client)
    # the normal collection API is scoped to the viewer, so sharing grants no write access
    assert client.patch(f"/api/collection/{item_id}", json={"notes": "hacked"}).status_code == 404
    assert client.delete(f"/api/collection/{item_id}").status_code == 404
    # you don't see yourself in the list
    client.put("/api/auth/sharing", json={"share_collection": True})
    assert [s["username"] for s in client.get("/api/shared").json()] == ["admin"]


def test_unsharing_and_disabled_users_disappear(two_users):
    client, admin_id = two_users
    client.put("/api/auth/sharing", json={"share_collection": True})
    client.put("/api/auth/sharing", json={"share_collection": False})
    _as_bob(client)
    assert client.get("/api/shared").json() == []
    assert client.get(f"/api/shared/{admin_id}/collection").status_code == 404
