"""Collection import from spreadsheet rows.

The browser parses the file and sends rows as {column: text}; `mapping` says which column
feeds which field. Import is local and fast; linking to PriceCharting happens afterwards
in the background (see autolink.py) so large files don't sit behind the rate limiter.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectionItem, Platform, Product
from app.models.enums import Category, Condition, ItemStatus
from app.pricing.pricecharting import console_slug_from_url, is_pricecharting_url

FIELDS = [
    "title", "platform", "category", "region", "status", "condition", "quantity",
    "has_item", "has_box", "has_manual", "has_inserts", "grade",
    "purchase_price", "purchase_date", "sold_price", "sold_date", "target_price",
    "location", "tags", "notes", "pricecharting_url", "upc",
]  # fmt: skip

# Header names (normalized) that auto-map to a field.
HEADER_HINTS = {
    "title": ["title", "name", "game", "gamename", "gametitle", "productname", "product", "item"],
    "platform": ["platform", "console", "consolename", "system", "systemname"],
    "category": ["category", "type", "itemtype"],
    "region": ["region"],
    "status": ["status", "list", "ownership"],
    "condition": ["condition", "completeness", "cond"],
    "quantity": ["quantity", "qty", "count", "copies"],
    "has_item": ["hasitem", "cart", "cartridge", "disc", "game"],
    "has_box": ["hasbox", "box", "boxed"],
    "has_manual": ["hasmanual", "manual"],
    "has_inserts": ["hasinserts", "inserts"],
    "grade": ["grade"],
    "purchase_price": ["purchaseprice", "price", "paid", "pricepaid", "cost", "pricepaidusd"],
    "purchase_date": ["purchasedate", "datepurchased", "bought", "dateacquired", "acquired", "date"],
    "sold_price": ["soldprice", "saleprice"],
    "sold_date": ["solddate", "datesold"],
    "target_price": ["targetprice", "target", "maxprice"],
    "location": ["location", "shelf", "storage"],
    "tags": ["tags", "tag", "labels"],
    "notes": ["notes", "note", "comments", "comment"],
    "pricecharting_url": ["pricechartingurl", "pricecharting", "url", "link"],
    "upc": ["upc", "barcode", "ean"],
}

CONDITION_WORDS = {
    Condition.loose: ["loose", "cartonly", "disconly", "gameonly", "used", "cart", "disc", "l"],
    Condition.cib: ["cib", "complete", "completeinbox", "boxed", "c"],
    Condition.new: ["new", "sealed", "nib", "newinbox", "mint", "n"],
    Condition.graded: ["graded", "wata", "vga", "cgc"],
    Condition.box_only: ["boxonly", "box"],
    Condition.manual_only: ["manualonly", "manual"],
}
STATUS_WORDS = {
    ItemStatus.owned: ["owned", "own", "have", "collection", "yes", "in collection", "incollection"],
    ItemStatus.wishlist: ["wishlist", "wish", "want", "wanted", "wantlist"],
    ItemStatus.sold: ["sold", "gone", "traded"],
}
CATEGORY_WORDS = {
    Category.game: ["game", "games", "videogame", "software"],
    Category.console: ["console", "system", "hardware", "consoles"],
    Category.pc_big_box: ["pcbigbox", "bigbox"],
    Category.controller: ["controller", "controllers", "gamepad", "pad"],
    Category.accessory: ["accessory", "accessories", "peripheral"],
    Category.other: ["other", "misc", "merch"],
}
# Common platform names that don't normalize onto a seeded name/slug.
PLATFORM_ALIASES = {
    "snes": "snes", "supernes": "snes", "supernintendoentertainmentsystem": "snes",
    "nintendoentertainmentsystem": "nes", "famicom": "famicom",
    "n64": "n64", "gamecube": "gamecube", "gcn": "gamecube", "ngc": "gamecube",
    "nintendogamecube": "gamecube",
    "gb": "game-boy", "gbc": "game-boy-color", "gba": "game-boy-advance",
    "ds": "nintendo-ds", "nds": "nintendo-ds",
    "3ds": "nintendo-3ds", "switch": "switch", "nintendoswitch": "switch", "switch2": "switch-2",
    "wiiu": "wii-u", "nintendowii": "wii", "nintendowiiu": "wii-u",
    "ps1": "ps1", "psx": "ps1", "psone": "ps1", "playstation1": "ps1", "sonyplaystation": "ps1",
    "ps2": "ps2", "ps3": "ps3", "ps4": "ps4", "ps5": "ps5", "vita": "ps-vita", "psvita": "ps-vita",
    "genesis": "genesis", "megadrive": "genesis", "segagenesis": "genesis", "segamegadrive": "genesis",
    "mastersystem": "master-system", "sms": "master-system", "saturn": "saturn", "dreamcast": "dreamcast",
    "dc": "dreamcast", "gamegear": "game-gear", "segacd": "sega-cd", "32x": "sega-32x",
    "xbox360": "xbox-360", "x360": "xbox-360", "xboxone": "xbox-one", "xbone": "xbox-one",
    "xboxseriesx": "xbox-series", "xboxseriess": "xbox-series", "xboxseriesxs": "xbox-series",
    "xsx": "xbox-series",
    "originalxbox": "xbox", "atari2600": "atari-2600", "2600": "atari-2600", "7800": "atari-7800",
    "5200": "atari-5200", "lynx": "atari-lynx", "jaguar": "jaguar", "tg16": "turbografx-16",
    "turbografx": "turbografx-16", "pcengine": "pc-engine", "neogeo": "neo-geo-aes",
    "ngpc": "neo-geo-pocket-color",
    "pc": "pc", "windows": "pc", "dos": "pc", "pcgames": "pc", "steam": "pc",
}  # fmt: skip
TRUE_WORDS = {"y", "yes", "true", "1", "x", "✓", "✔", "t"}
FALSE_WORDS = {"n", "no", "false", "0", "", "f", "-"}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """field -> column, best guess from header names."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    normalized = {h: norm(h) for h in headers}
    # exact field names first (round-trips our own export), then hints in priority order
    for f in FIELDS:
        for h, n in normalized.items():
            if n == norm(f) and h not in used:
                mapping[f] = h
                used.add(h)
                break
    for f, hints in HEADER_HINTS.items():
        if f in mapping:
            continue
        for hint in hints:
            h = next((h for h, n in normalized.items() if n == hint and h not in used), None)
            if h:
                mapping[f] = h
                used.add(h)
                break
    return mapping


def _word_lookup(table: dict, value: str):
    n = norm(value)
    for key, words in table.items():
        if n == norm(key) or n in words:
            return key
    return None


BLANKS = {"", "-", "--", "n/a", "na", "none", "null", "?"}


def parse_money(value: str) -> Decimal | None:
    if (value or "").strip().lower() in BLANKS:
        return None
    cleaned = re.sub(r"[^\d.,-]", "", value)
    if not re.search(r"\d", cleaned):
        raise ValueError(f"not a price: {value!r}")
    if "," in cleaned and "." not in cleaned and re.search(r",\d{2}$", cleaned):
        cleaned = cleaned.replace(",", ".")  # 12,50 -> 12.50
    cleaned = cleaned.replace(",", "")
    try:
        v = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a price: {value!r}") from None
    if v < 0:
        raise ValueError(f"negative price: {value!r}")
    return v.quantize(Decimal("0.01"))


DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
]


def parse_date(value: str, day_first: bool = False) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    value = value.split("T")[0].split(" ")[0] if re.match(r"\d{4}-\d{2}-\d{2}[T ]", value) else value
    formats = DATE_FORMATS
    if day_first:
        formats = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", *DATE_FORMATS[3:]]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {value!r}")


def parse_bool(value: str) -> bool | None:
    n = (value or "").strip().lower()
    if n in TRUE_WORDS:
        return True
    if n in FALSE_WORDS:
        return False
    raise ValueError(f"not yes/no: {value!r}")


REGION_WORDS = {
    "pal": "PAL", "eu": "PAL", "eur": "PAL", "europe": "PAL", "european": "PAL", "uk": "PAL",
    "au": "PAL", "aus": "PAL", "australia": "PAL",
    "jp": "NTSC-J", "jpn": "NTSC-J", "jap": "NTSC-J", "japan": "NTSC-J", "japanese": "NTSC-J",
    "ntscj": "NTSC-J",
    "us": "NTSC-U", "usa": "NTSC-U", "na": "NTSC-U", "ntsc": "NTSC-U", "ntscu": "NTSC-U",
    "northamerica": "NTSC-U",
}  # fmt: skip
# Japanese counterparts that are their own platforms rather than "<base>-jp".
JP_EQUIVALENTS = {"nes": "famicom", "snes": "super-famicom", "turbografx-16": "pc-engine"}


def parse_region(value: str | None) -> str | None:
    n = norm(value)
    return REGION_WORDS.get(n) or {"pal": "PAL", "ntscj": "NTSC-J", "ntscu": "NTSC-U"}.get(n)


def _base_slug(slug: str) -> str:
    for suffix in ("-pal", "-jp"):
        if slug.endswith(suffix):
            return slug[: -len(suffix)]
    return {v: k for k, v in JP_EQUIVALENTS.items()}.get(slug, slug)


class PlatformMatcher:
    """Match free-text platform names, including region words ("N64 PAL", "Japanese Saturn")."""

    def __init__(self, db: Session):
        self.by_key: dict[str, Platform] = {}
        platforms = list(db.scalars(select(Platform)))
        by_slug = {p.slug: p for p in platforms}
        for p in platforms:
            for key in (p.name, p.slug, p.pricecharting_slug, f"{p.brand}{p.name}"):
                if key:
                    self.by_key.setdefault(norm(key), p)
        for alias, slug in PLATFORM_ALIASES.items():
            if slug in by_slug:
                self.by_key.setdefault(alias, by_slug[slug])
        self.by_pc_slug = {p.pricecharting_slug: p for p in platforms if p.pricecharting_slug}
        self.variants = {(_base_slug(p.slug), p.region): p for p in platforms}

    def _lookup(self, name: str) -> tuple[Platform | None, str | None]:
        p = self.by_key.get(norm(name))
        if p:
            return p, None
        # Strip region words ("PAL", "(JP)", "Japanese") and try again.
        words = re.findall(r"[a-z0-9]+", name.lower())
        region = next((REGION_WORDS[w] for w in words if w in REGION_WORDS), None)
        rest = "".join(w for w in words if w not in REGION_WORDS)
        return (self.by_key.get(rest) if rest else None), region

    def in_region(self, platform: Platform, region: str | None) -> Platform:
        if not region or platform.region == region:
            return platform
        return self.variants.get((_base_slug(platform.slug), region), platform)

    def match(
        self,
        name: str | None,
        url: str | None = None,
        region: str | None = None,
        default_region: str | None = None,
    ) -> Platform | None:
        """`region` (e.g. from a Region column) wins over words in the name; `default_region`
        applies only when neither the name nor the column says."""
        if url:
            p = self.by_pc_slug.get(console_slug_from_url(url) or "")
            if p:
                return p
        if not name:
            return None
        platform, named_region = self._lookup(name)
        if platform is None:
            return None
        explicit = region or named_region
        if explicit:
            return self.in_region(platform, explicit)
        # A bare name that is itself regional ("Super Famicom") keeps its region.
        if platform.region != "NTSC-U" or not default_region:
            return platform
        return self.in_region(platform, default_region)


@dataclass
class RowResult:
    index: int
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    platform_id: int | None = None
    platform_name: str | None = None
    product_id: int | None = None  # existing catalog product it will use
    duplicate: bool = False


@dataclass
class Options:
    mapping: dict[str, str]
    default_status: ItemStatus = ItemStatus.owned
    default_condition: Condition = Condition.loose
    default_platform_id: int | None = None
    default_category: Category = Category.game
    day_first: bool = False
    skip_duplicates: bool = True
    default_region: str = "NTSC-U"


def _cell(row: dict[str, str], mapping: dict[str, str], f: str) -> str:
    col = mapping.get(f)
    return (row.get(col) or "").strip() if col else ""


def analyze(db: Session, user_id: int, rows: list[dict[str, str]], opts: Options) -> list[RowResult]:
    matcher = PlatformMatcher(db)
    default_platform = db.get(Platform, opts.default_platform_id) if opts.default_platform_id else None
    # Existing catalog, for de-duplicating products
    catalog_by_title = {
        (norm(t), pid): prod_id
        for prod_id, t, pid in db.execute(select(Product.id, Product.title, Product.platform_id)).all()
    }
    catalog_by_url = dict(
        db.execute(
            select(Product.pricecharting_url, Product.id).where(Product.pricecharting_url.is_not(None))
        ).all()
    )
    catalog_by_upc = dict(db.execute(select(Product.upc, Product.id).where(Product.upc.is_not(None))).all())
    owned = {
        (pid, cond, status)
        for pid, cond, status in db.execute(
            select(CollectionItem.product_id, CollectionItem.condition, CollectionItem.status).where(
                CollectionItem.user_id == user_id
            )
        ).all()
    }
    seen_in_file: set[tuple] = set()

    results = []
    for i, row in enumerate(rows):
        r = RowResult(index=i)

        def cell(f: str, row: dict[str, str] = row) -> str:
            return _cell(row, opts.mapping, f)

        v = r.values

        title = cell("title")
        url = cell("pricecharting_url")
        if url and not is_pricecharting_url(url):
            r.warnings.append("PriceCharting URL ignored (not a pricecharting.com/game/ link)")
            url = ""
        if not title and not url:
            r.errors.append("missing title")
        v["title"] = title
        v["pricecharting_url"] = url or None

        region_raw = cell("region")
        region = parse_region(region_raw) if region_raw else None
        if region_raw and region is None:
            r.warnings.append(f"region {region_raw!r} not recognized (use NTSC-U, PAL or NTSC-J)")
        platform = matcher.match(cell("platform"), url or None, region, opts.default_region)
        if platform is None and cell("platform"):
            if default_platform:
                r.warnings.append(f"unknown platform {cell('platform')!r}, using {default_platform.name}")
            else:
                r.errors.append(f"unknown platform {cell('platform')!r}")
        platform = platform or default_platform
        if platform is None and "unknown platform" not in " ".join(r.errors):
            r.errors.append("missing platform")
        elif platform and opts.default_platform_id and not cell("platform"):
            platform = matcher.in_region(platform, region)
        if platform:
            r.platform_id, r.platform_name = platform.id, platform.name

        for f, table, default in (
            ("condition", CONDITION_WORDS, opts.default_condition),
            ("status", STATUS_WORDS, opts.default_status),
            ("category", CATEGORY_WORDS, opts.default_category),
        ):
            raw = cell(f)
            parsed = _word_lookup(table, raw) if raw else None
            if raw and parsed is None:
                r.warnings.append(f"{f} {raw!r} not recognized, using {default.value}")
            v[f] = (parsed or default).value

        try:
            qty = cell("quantity")
            v["quantity"] = int(float(qty)) if qty else 1
            if v["quantity"] < 1:
                raise ValueError
        except ValueError:
            r.errors.append(f"bad quantity {cell('quantity')!r}")

        for f in ("purchase_price", "sold_price", "target_price"):
            try:
                v[f] = parse_money(cell(f))
            except ValueError as e:
                r.errors.append(f"{f.replace('_', ' ')}: {e}")
        for f in ("purchase_date", "sold_date"):
            try:
                v[f] = parse_date(cell(f), opts.day_first)
            except ValueError as e:
                r.errors.append(f"{f.replace('_', ' ')}: {e}")
        for f in ("has_item", "has_box", "has_manual", "has_inserts"):
            raw = cell(f)
            if raw:
                try:
                    v[f] = parse_bool(raw)
                except ValueError as e:
                    r.warnings.append(f"{f}: {e}, ignored")
        # Sensible component defaults from condition when not given
        v.setdefault("has_item", v["condition"] not in ("box_only", "manual_only"))
        v.setdefault("has_box", v["condition"] in ("cib", "new", "box_only"))
        v.setdefault("has_manual", v["condition"] in ("cib", "new", "manual_only"))
        v.setdefault("has_inserts", False)

        upc = re.sub(r"\D", "", cell("upc"))
        v["upc"] = upc if 8 <= len(upc) <= 14 else None
        tags = cell("tags")
        v["tags"] = [t.strip() for t in re.split(r"[;,|]", tags) if t.strip()] if tags else []
        v["region"] = None  # the platform carries the region
        for f in ("grade", "location", "notes"):
            v[f] = cell(f) or None

        if r.platform_id:
            r.product_id = (
                (url and catalog_by_url.get(url))
                or (v["upc"] and catalog_by_upc.get(v["upc"]))
                or catalog_by_title.get((norm(title), r.platform_id))
                or None
            )
            key = (r.product_id or (norm(title), r.platform_id), v["condition"], v["status"])
            if (r.product_id, v["condition"], v["status"]) in owned or key in seen_in_file:
                r.duplicate = True
                r.warnings.append(
                    "already in your collection" if key not in seen_in_file else "duplicate row"
                )
            seen_in_file.add(key)

        r.ok = not r.errors
        results.append(r)
    return results


def commit(db: Session, user_id: int, rows: list[dict[str, str]], opts: Options) -> dict:
    results = analyze(db, user_id, rows, opts)
    created_items = created_products = skipped = failed = 0
    new_products: dict[tuple, Product] = {}
    for r in results:
        if not r.ok:
            failed += 1
            continue
        if r.duplicate and opts.skip_duplicates:
            skipped += 1
            continue
        v = r.values
        product_id = r.product_id
        if product_id is None:
            key = (v["pricecharting_url"] or norm(v["title"]), r.platform_id)
            product = new_products.get(key)
            if product is None:
                product = Product(
                    title=v["title"] or "Untitled",
                    platform_id=r.platform_id,
                    category=v["category"],
                    region=v["region"],
                    upc=v["upc"],
                    pricecharting_url=v["pricecharting_url"],
                )
                db.add(product)
                db.flush()
                new_products[key] = product
                created_products += 1
            product_id = product.id
        db.add(
            CollectionItem(
                user_id=user_id,
                product_id=product_id,
                **{
                    k: v[k]
                    for k in (
                        "status",
                        "condition",
                        "quantity",
                        "has_item",
                        "has_box",
                        "has_manual",
                        "has_inserts",
                        "grade",
                        "purchase_price",
                        "purchase_date",
                        "sold_price",
                        "sold_date",
                        "target_price",
                        "location",
                        "tags",
                        "notes",
                    )
                },  # fmt: skip
            )
        )
        created_items += 1
    db.commit()
    unlinked = db.scalar(
        select(func.count(func.distinct(Product.id)))
        .join(CollectionItem, CollectionItem.product_id == Product.id)
        .where(CollectionItem.user_id == user_id, Product.pricecharting_url.is_(None))
    )
    return {
        "created_items": created_items,
        "created_products": created_products,
        "skipped": skipped,
        "failed": failed,
        "unlinked": unlinked or 0,
    }
