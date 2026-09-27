import csv
import io
import sqlite3

from app.services import backups
from tests.conftest import login


def _add(client, title, **fields):
    platform = next(p["id"] for p in client.get("/api/platforms").json() if p["slug"] == "snes")
    product = client.post("/api/products", json={"title": title, "platform_id": platform}).json()
    return client.post("/api/collection", json={"product_id": product["id"], **fields}).json()


def test_export_csv_and_json(admin):
    _add(admin, "Super Metroid", condition="cib", purchase_price="40", tags=["fav", "rpg"], notes="Ünïcode ✓")
    _add(admin, "Wanted", status="wishlist", target_price="20")

    r = admin.get("/api/collection/export", params={"format": "csv"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["title"] for row in rows] == ["Super Metroid", "Wanted"]
    assert rows[0]["tags"] == "fav; rpg" and rows[0]["notes"] == "Ünïcode ✓"
    assert rows[0]["platform"] == "Super Nintendo" and rows[0]["condition"] == "cib"

    data = admin.get("/api/collection/export", params={"format": "json", "status": "wishlist"}).json()
    assert [d["title"] for d in data] == ["Wanted"] and data[0]["target_price"] == "20.00"


def test_backup_create_list_download_prune(admin):
    for b in backups.list_backups():
        (backups.backup_dir() / b["name"]).unlink()

    r = admin.post("/api/admin/backups")
    assert r.status_code == 201, r.text
    name = r.json()["name"]

    listing = admin.get("/api/admin/backups").json()
    assert listing["supported"] is True and [b["name"] for b in listing["backups"]] == [name]

    # The backup is a valid SQLite DB with our tables
    path = backups.resolve(name)
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    finally:
        conn.close()
    assert {"users", "collection_items", "price_snapshots"} <= tables

    assert admin.get(f"/api/admin/backups/{name}").content[:16] == b"SQLite format 3\x00"
    assert admin.get("/api/admin/backups/..%2Fvgvault.db").status_code == 404

    # Retention
    for i in range(3):
        (backups.backup_dir() / f"vgvault-2000010{i}-000000.db").write_bytes(b"x")
    assert backups.prune(2) == 2
    assert len(backups.list_backups()) == 2

    assert admin.delete(f"/api/admin/backups/{name}").status_code == 204


def test_backup_settings_and_admin_only(admin):
    s = admin.get("/api/admin/backups").json()["settings"]
    s["keep"] = 3
    assert admin.put("/api/admin/backups/settings", json=s).json()["keep"] == 3
    s["cron"] = "bad"
    assert admin.put("/api/admin/backups/settings", json=s).status_code == 422

    admin.post("/api/users", json={"username": "bob", "password": "password123"})
    login(admin, "bob")
    assert admin.get("/api/admin/backups").status_code == 403
    assert admin.post("/api/admin/backups").status_code == 403
