from tests.conftest import login


def _platform_id(client, slug="n64"):
    return next(p["id"] for p in client.get("/api/platforms").json() if p["slug"] == slug)


def _add_game(client, title, slug="n64", **item):
    product = client.post(
        "/api/products", json={"title": title, "platform_id": _platform_id(client, slug)}
    ).json()
    r = client.post("/api/collection", json={"product_id": product["id"], **item})
    assert r.status_code == 201, r.text
    return r.json()


def test_setup_flow(client):
    assert client.get("/api/setup/status").json()["needs_setup"] is True
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/setup", json={"username": "admin", "password": "password123"})
    assert r.json()["role"] == "admin"
    assert client.get("/api/auth/me").json()["username"] == "admin"
    assert client.post("/api/setup", json={"username": "xyz", "password": "password123"}).status_code == 409


def test_platforms_seeded(admin):
    platforms = admin.get("/api/platforms").json()
    assert len(platforms) > 50
    n64 = next(p for p in platforms if p["slug"] == "n64")
    assert n64["brand"] == "Nintendo" and n64["media_type"] == "cartridge"


def test_admin_user_management_and_isolation(admin):
    r = admin.post("/api/users", json={"username": "bob", "password": "password123"})
    assert r.status_code == 201
    _add_game(admin, "Super Mario 64")

    login(admin, "bob")
    assert admin.get("/api/users").status_code == 403
    assert admin.get("/api/collection").json()["total"] == 0
    _add_game(admin, "GoldenEye 007")
    assert admin.get("/api/collection").json()["total"] == 1


def test_cannot_demote_last_admin(admin):
    me = admin.get("/api/auth/me").json()
    r = admin.patch(f"/api/users/{me['id']}", json={"role": "user"})
    assert r.status_code == 400


def test_password_reset_invalidates_session(admin):
    bob = admin.post("/api/users", json={"username": "bob", "password": "password123"}).json()
    admin_cookies = dict(admin.cookies)
    login(admin, "bob")
    assert admin.get("/api/auth/me").status_code == 200
    bob_cookies = dict(admin.cookies)

    admin.cookies.clear()
    admin.cookies.update(admin_cookies)
    admin.patch(f"/api/users/{bob['id']}", json={"password": "newpassword1"})

    admin.cookies.clear()
    admin.cookies.update(bob_cookies)
    assert admin.get("/api/auth/me").status_code == 401


def test_collection_filters(admin):
    _add_game(admin, "Super Mario 64", "n64", condition="cib", purchase_price="40", tags=["favorite"])
    _add_game(admin, "Halo", "xbox", condition="loose", purchase_price="5")
    _add_game(admin, "Final Fantasy VII", "ps1", status="wishlist")

    def titles(**params):
        return sorted(
            i["product"]["title"] for i in admin.get("/api/collection", params=params).json()["items"]
        )

    assert titles(brand="Nintendo") == ["Super Mario 64"]
    assert titles(media_type="disc") == ["Final Fantasy VII", "Halo"]
    assert titles(status="wishlist") == ["Final Fantasy VII"]
    assert titles(tag="favorite") == ["Super Mario 64"]
    assert titles(q="halo") == ["Halo"]
    assert titles(era="6th Gen") == ["Halo"]
    items = admin.get("/api/collection", params={"sort": "purchase_price", "order": "desc"}).json()["items"]
    assert [i["product"]["title"] for i in items] == ["Super Mario 64", "Halo", "Final Fantasy VII"]

    summary = admin.get("/api/collection/summary").json()
    assert summary == {"items": 2, "quantity": 2, "cost_basis": 45.0, "total_value": 0.0, "unpriced": 2}

    facets = admin.get("/api/collection/facets").json()
    assert facets["brands"] == ["Microsoft", "Nintendo", "Sony"]


def test_condition_rating_filter_and_sort(admin):
    # Overall condition = lowest rating among parts the item has.
    _add_game(admin, "Mint", condition="cib", has_box=True, has_manual=True, item_rating=10, box_rating=9)
    _add_game(admin, "Rough box", condition="cib", has_box=True, item_rating=10, box_rating=3)
    _add_game(admin, "Box gone", item_rating=7, box_rating=2)  # box rating ignored: no box
    _add_game(admin, "Unrated")

    def titles(**params):
        return [i["product"]["title"] for i in admin.get("/api/collection", params=params).json()["items"]]

    assert titles(rating="mint") == ["Mint"]
    assert titles(rating="excellent") == ["Box gone"]
    assert sorted(titles(rating=["poor", "unrated"])) == ["Rough box", "Unrated"]
    assert titles(sort="rating", order="desc") == ["Mint", "Box gone", "Rough box", "Unrated"]


def test_bulk_update_and_delete(admin):
    a = _add_game(admin, "A")
    b = _add_game(admin, "B")
    r = admin.patch(
        "/api/collection/bulk", json={"ids": [a["id"], b["id"]], "changes": {"location": "Shelf 1"}}
    )
    assert r.status_code == 200 and all(i["location"] == "Shelf 1" for i in r.json())
    assert admin.delete(f"/api/collection/{a['id']}").status_code == 204
    assert admin.get("/api/collection").json()["total"] == 1
