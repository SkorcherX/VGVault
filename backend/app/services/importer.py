"""Collection import from spreadsheet rows.

The browser parses the file and sends rows as {column: text}; `mapping` says which column
feeds which field. Import is local and fast; linking to PriceCharting happens afterwards
in the background (see autolink.py) so large files don't sit behind the rate limiter.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectionItem, Platform, Product
from app.models.enums import Category, Condition, ItemStatus
from app.pricing.pricecharting import console_slug_from_url, normalize_pricecharting_url

FIELDS = [
    "title", "platform", "category", "region", "status", "condition", "quantity",
    "has_item", "has_box", "has_manual", "has_inserts", "grade",
    "item_rating", "box_rating", "manual_rating",
    "purchase_price", "purchase_date", "sold_price", "sold_date", "target_price",
    "location", "acquired_from", "tags", "notes", "pricecharting_url", "upc",
]  # fmt: skip

# Header names (normalized) that auto-map to a field.
HEADER_HINTS = {
    "title": ["title", "name", "game", "gamename", "gametitle", "productname", "product", "item"],
    "platform": ["platform", "console", "consolename", "system", "systemname"],
    "category": ["category", "type", "itemtype"],
    "region": ["region", "country"],
    "status": ["status", "list", "userrecordtype", "recordtype"],
    "condition": ["condition", "completeness", "cond", "ownership"],
    "quantity": ["quantity", "qty", "count", "copies", "amount", "number", "owned"],
    "has_item": ["hasitem", "cart", "cartridge", "disc", "game"],
    "has_box": ["hasbox", "box", "boxed"],
    "has_manual": ["hasmanual", "manual"],
    "has_inserts": ["hasinserts", "inserts"],
    "grade": ["grade"],
    "item_rating": ["itemrating", "itemcondition", "cartcondition", "disccondition", "gamecondition"],
    "box_rating": ["boxrating", "boxcondition"],
    "manual_rating": ["manualrating", "manualcondition"],
    # Not "value": in hand-kept sheets that's a looked-up market value, not what was paid.
    "purchase_price": ["purchaseprice", "price", "paid", "pricepaid", "cost", "pricepaidusd"],
    "purchase_date": [
        "purchasedate",
        "datepurchased",
        "dateacquired",
        "acquired",
        "dateadded",
        "added",
        "createdat",
        "date",
    ],
    "sold_price": ["soldprice", "saleprice", "pricesold"],
    "sold_date": ["solddate", "datesold"],
    "target_price": ["targetprice", "target", "maxprice"],
    "location": ["location", "shelf", "storage"],
    "acquired_from": [
        "acquiredfrom",
        "boughtfrom",
        "purchasedfrom",
        "purchasedat",
        "purchased",
        "source",
        "store",
        "seller",
        "where",
        "bought",
    ],
    "tags": ["tags", "tag", "labels"],
    "notes": ["notes", "note", "comments", "comment"],
    "pricecharting_url": ["pricechartingurl", "pricecharting", "url", "link"],
    "upc": ["upc", "barcode", "ean"],
}

CONDITION_WORDS = {
    Condition.loose: ["loose", "cartonly", "disconly", "gameonly", "used", "cart", "disc", "l", "digital"],
    Condition.cib: ["cib", "complete", "completeinbox", "boxed", "c"],
    Condition.new: ["new", "sealed", "nib", "newinbox", "sib", "sealedinbox", "mint", "n"],
    Condition.graded: ["graded", "wata", "vga", "cgc"],
    Condition.box_only: ["boxonly", "box"],
    Condition.manual_only: ["manualonly", "manual", "m"],
}
STATUS_WORDS = {
    ItemStatus.owned: ["owned", "own", "have", "collection", "yes", "in collection", "incollection"],
    ItemStatus.wishlist: ["wishlist", "wish", "want", "wanted", "wantlist"],
    ItemStatus.sold: ["sold", "gone", "traded"],
}
CATEGORY_WORDS = {
    Category.game: ["game", "games", "videogame", "software"],
    Category.console: ["console", "system", "hardware", "consoles", "systems"],
    Category.pc_big_box: ["pcbigbox", "bigbox"],
    Category.controller: ["controller", "controllers", "gamepad", "pad"],
    Category.accessory: ["accessory", "accessories", "peripheral", "gameaccessories"],
    Category.other: [
        "other",
        "misc",
        "merch",
        "printmedia",
        "book",
        "books",
        "guide",
        "strategyguide",
        "magazine",
        "toystolife",
        "amiibo",
        "figure",
        "figures",
    ],
}
# Common platform names that don't normalize onto a seeded name/slug.
PLATFORM_ALIASES = {
    "snes": "snes", "supernes": "snes", "supernintendoentertainmentsystem": "snes",
    "nintendoentertainmentsystem": "nes", "famicom": "famicom",
    "n64": "n64", "gamecube": "gamecube", "gcn": "gamecube", "ngc": "gamecube",
    "nintendogamecube": "gamecube",
    "gb": "game-boy", "gbc": "game-boy-color", "gba": "game-boy-advance",
    "ds": "nintendo-ds", "nds": "nintendo-ds",
    "3ds": "nintendo-3ds", "n3ds": "nintendo-3ds", "new3ds": "nintendo-3ds",
    "newnintendo3ds": "nintendo-3ds", "3dsxl": "nintendo-3ds", "gameboyclassic": "game-boy",
    "switch": "switch", "nintendoswitch": "switch", "switch2": "switch-2",
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
    # GamEye names
    "nesfamicom": "nes", "snessuperfamicom": "snes", "segagenesismegadrive": "genesis",
    "turbografx16cd": "turbografx-cd", "turbografxcd": "turbografx-cd", "segacdmegacd": "sega-cd",
    "turbografx16pcengine": "turbografx-16", "nintendo64dd": "n64", "64dd": "n64",
    "atarijaguarcd": "jaguar", "jaguarcd": "jaguar", "segacd32x": "sega-cd",
    "strategyguides": "strategy-guide",
    "nintendopower": "magazines", "electronicgamingmonthly": "magazines", "egm": "magazines",
    "gamepro": "magazines", "gameinformer": "magazines", "magazine": "magazines",
    "pc": "pc", "windows": "pc", "dos": "pc", "pcgames": "pc", "steam": "pc",
}  # fmt: skip
TRUE_WORDS = {"y", "yes", "true", "1", "x", "✓", "✔", "t"}
FALSE_WORDS = {"n", "no", "false", "0", "", "f", "-"}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def suggest_mapping(headers: list[str], rows: list[dict[str, str]] | None = None) -> dict[str, str]:
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
    if rows:
        _refine_with_data(mapping, used, headers, rows)
    return mapping


def _column_values(rows: list[dict[str, str]], column: str, limit: int = 300) -> list[str]:
    out = []
    for row in rows:
        v = (row.get(column) or "").strip()
        if v:
            out.append(v)
            if len(out) >= limit:
                break
    return out


def _refine_with_data(
    mapping: dict[str, str], used: set[str], headers: list[str], rows: list[dict[str, str]]
) -> None:
    """Use cell values where header names are ambiguous or missing."""
    values = {h: _column_values(rows, h) for h in headers}
    # A column that is one repeated label (e.g. "Lookup" link text) isn't real notes/tags.
    for f in ("notes", "tags", "location", "grade"):
        col = mapping.get(f)
        is_link_label = col and f"{col} (link)" in headers and len(set(values[col])) <= 1
        if col and (is_link_label or (len(values[col]) >= 5 and len(set(values[col])) == 1)):
            del mapping[f]
            used.discard(col)
    # Columns of PriceCharting links
    if "pricecharting_url" not in mapping:
        for h in headers:
            vals = values[h]
            if (
                h not in used
                and vals
                and sum(normalize_pricecharting_url(v) is not None for v in vals) >= 0.5 * len(vals)
            ):
                mapping["pricecharting_url"] = h
                used.add(h)
                break
    # Recognize condition/status/category columns by their contents ("Rating" = Loose/CIB/...)
    for f, table in (("condition", CONDITION_WORDS), ("status", STATUS_WORDS), ("category", CATEGORY_WORDS)):
        if f in mapping:
            continue
        for h in headers:
            vals = values[h]
            if (
                h not in used
                and len(vals) >= 3
                and sum(_word_lookup(table, v) is not None for v in vals) >= 0.8 * len(vals)
            ):
                mapping[f] = h
                used.add(h)
                break
    # One tab per platform: the sheet name is the platform
    if "platform" not in mapping and "Sheet name" in headers:
        mapping["platform"] = "Sheet name"
        used.add("Sheet name")


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
    try:
        return float(n) > 0  # numeric scores, e.g. 10 = present, 0 = missing
    except ValueError:
        pass
    if n in TRUE_WORDS:
        return True
    if n in FALSE_WORDS:
        return False
    raise ValueError(f"not yes/no: {value!r}")


def parse_rating(value: str) -> int | None:
    """1-10 condition score. Accepts 0-1 fractions (GamEye: 0.8), 1-10, or percentages."""
    if (value or "").strip().lower() in BLANKS:
        return None
    try:
        n = float(value.strip().rstrip("%"))
    except ValueError:
        raise ValueError(f"not a 1-10 rating: {value!r}") from None
    if value.strip().endswith("%") or n > 10:
        n /= 10
    elif n <= 1 and "." in value:
        n *= 10
    if not 0 <= n <= 10:
        raise ValueError(f"not a 1-10 rating: {value!r}")
    return max(1, int(n + 0.5)) if n else None


REGION_WORDS = {
    "pal": "PAL", "eu": "PAL", "eur": "PAL", "europe": "PAL", "european": "PAL", "uk": "PAL",
    "au": "PAL", "aus": "PAL", "australia": "PAL",
    "jp": "NTSC-J", "jpn": "NTSC-J", "jap": "NTSC-J", "japan": "NTSC-J", "japanese": "NTSC-J",
    "ntscj": "NTSC-J",
    "us": "NTSC-U", "usa": "NTSC-U", "na": "NTSC-U", "ntsc": "NTSC-U", "ntscu": "NTSC-U",
    "northamerica": "NTSC-U",
    # Country names (GamEye exports a Country column)
    "unitedstatesofamerica": "NTSC-U", "unitedstates": "NTSC-U", "america": "NTSC-U",
    "canada": "NTSC-U", "mexico": "NTSC-U",
    "unitedkingdom": "PAL", "greatbritain": "PAL", "england": "PAL", "germany": "PAL",
    "france": "PAL", "italy": "PAL", "spain": "PAL", "netherlands": "PAL", "sweden": "PAL",
    "newzealand": "PAL", "ireland": "PAL",
}  # fmt: skip
NO_REGION_WORDS = {"world", "worldwide", "global", "international", "regionfree", "all"}
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
        # Several platforms can share one PriceCharting console (Genesis and Nomad): keep all,
        # oldest first, so the original platform wins unless the row names another.
        self.by_pc_slug: dict[str, list[Platform]] = {}
        for p in sorted(platforms, key=lambda p: p.id):
            if p.pricecharting_slug:
                self.by_pc_slug.setdefault(p.pricecharting_slug, []).append(p)
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

    def find_in_text(
        self, text: str, region: str | None = None, default_region: str | None = None
    ) -> Platform | None:
        """The platform named inside free text, longest name first: "Sega Nomad", "Microsoft
        Xbox 360 (Premium 20GB)", "Super Gameboy Advance"."""
        n = norm(text)
        for key in sorted((k for k in self.by_key if len(k) >= 3), key=len, reverse=True):
            if key in n:
                return self.match_name(key, region, default_region)
        return None

    def for_url(self, url: str | None) -> list[Platform]:
        return self.by_pc_slug.get(console_slug_from_url(url) or "", []) if url else []

    def match(
        self,
        name: str | None,
        url: str | None = None,
        region: str | None = None,
        default_region: str | None = None,
    ) -> Platform | None:
        """`region` (e.g. from a Region column) wins over words in the name; `default_region`
        applies only when neither the name nor the column says. A link's console decides the
        platform, preferring the named one when several share that console."""
        linked = self.for_url(url)
        named = self._lookup(name)[0] if name else None
        if linked:
            if named and any(p.id == named.id for p in linked):
                return named
            return linked[0]
        return self.match_name(name, region, default_region)

    def match_name(
        self, name: str | None, region: str | None = None, default_region: str | None = None
    ) -> Platform | None:
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
    day_first: bool | None = None  # None: detect from the data
    skip_duplicates: bool = True
    default_region: str = "NTSC-U"
    # Prices in the sheet are the total for the row (all copies), not per copy.
    prices_per_row: bool = False


def detect_day_first(rows: list[dict[str, str]], columns: list[str]) -> bool:
    """True if any d/m/y-looking date has a first part over 12 (and none has a second part over 12)."""
    day_first = month_first = False
    for row in rows:
        for col in columns:
            m = re.match(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}\s*$", row.get(col) or "")
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                day_first |= a > 12
                month_first |= b > 12
    return day_first and not month_first


# (collection shelf, linked console): hardware that plays the other's games, so a link to the
# other console is plausible, e.g. a TurboGrafx-CD disc filed with TG16, a PS1 disc with PS2.
COMPATIBLE = {
    ("turbografx-16", "turbografx-cd"), ("genesis", "sega-cd"), ("genesis", "sega-32x"),
    ("ps2", "ps1"), ("ps3", "ps1"), ("ps3", "ps2"), ("ps5", "ps4"),
    ("game-boy-color", "game-boy"), ("game-boy-advance", "game-boy"), ("game-boy-advance", "game-boy-color"),
    ("nintendo-3ds", "nintendo-ds"), ("wii", "gamecube"), ("wii-u", "wii"), ("switch-2", "switch"),
    ("xbox-360", "xbox"), ("xbox-one", "xbox-360"), ("xbox-series", "xbox-one"),
}  # fmt: skip


def _same_hardware(named: Platform, linked: Platform) -> bool:
    a, b = _base_slug(named.slug), _base_slug(linked.slug)
    return a == b or (a, b) in COMPATIBLE


_STOPWORDS = {"the", "of", "and", "a", "an", "to", "in", "on", "for", "vs", "with"}
_ROMAN = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}


def _title_words(text: str) -> set[str]:
    text = unquote(text).lower().replace("&", " and ").replace("'", "")
    text = re.sub(r"(\d)[.,](\d)", r"\1\2", text)  # 1,000 / 1.000 / 2.0 -> 1000 / 20
    return {_ROMAN.get(w, w) for w in re.findall(r"[a-z0-9]+", text)} - _STOPWORDS


def _numbers_agree(a: set[str], b: set[str]) -> bool:
    """Every number on one side appears on the other (a 2-digit year matches its 4-digit form)."""

    def found(n: str, pool: set[str]) -> bool:
        return any(m == n or (len(n) == 2 and len(m) == 4 and m.endswith(n)) for m in pool)

    na, nb = {w for w in a if w.isdigit()}, {w for w in b if w.isdigit()}
    return not na or not nb or all(found(n, nb) for n in na) or all(found(n, na) for n in nb)


def link_matches_title(title: str, url: str) -> bool:
    """Loose check that a PriceCharting link is for this game, to catch copy-paste mistakes in
    spreadsheets ("Stealth" linking to Rocket Ranger, "Madden 97" to Madden 96) while allowing
    naming differences ("Madden 98" vs madden-nfl-98, "SoulBlazer" vs soul-blazer)."""
    slug = unquote(url.rstrip("/").rsplit("/", 1)[-1])
    if not title or not slug:
        return True
    t, s = _title_words(title), _title_words(slug.replace("-", " "))
    if not t or not s:
        return True  # nothing to compare
    if not _numbers_agree(t, s):
        return False  # "Madden 97" vs madden-96
    compact_t, compact_s = norm(unquote(title)), norm(slug)
    if compact_t and (compact_t in compact_s or compact_s in compact_t):
        return True
    return len(t & s) / min(len(t), len(s)) >= 0.5


_LOOSE_WORDS = {"loose", "cartonly", "disconly", "gameonly"}
_NEW_WORDS = {"sealed", "new", "nib", "sib"}
_CIB_WORDS = {"cib", "complete", "completeinbox"}


@dataclass
class TitleHints:
    title: str
    condition: Condition | None = None
    has_manual: bool | None = None
    extras: list[str] = field(default_factory=list)  # "with Guide", for notes


def _hint_words(text: str, hints: TitleHints) -> str:
    """Take condition words out of `text`, noting them in `hints`; return what's left."""
    kept = []
    for w in re.split(r"\s+", text.strip()):
        n = norm(w)
        if n in _LOOSE_WORDS:
            hints.condition = Condition.loose
        elif n in _NEW_WORDS:
            hints.condition = Condition.new
        elif n in _CIB_WORDS:
            hints.condition = Condition.cib
        elif w:
            kept.append(w)
    return " ".join(kept)


def title_hints(title: str) -> TitleHints:
    """Hand-kept sheets put condition in the title: "Desert Strike (Loose)", "Final Fantasy X
    (Sealed)", "Dragon Warrior W/ Manual", "Mortal Kombat (No Manual)", "R-Type, W/ Manual Loose".
    Strip those, and move extras ("W/ Guide") to notes. Editions ("(Big Box)") stay in the title."""
    hints = TitleHints(title)

    def paren(m: re.Match) -> str:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if not any(_is_hint(p) for p in parts):
            return m.group(0)  # "(Big Box)", "(Collectors)": part of the name
        for p in parts:
            _apply_hint(p, hints)
        return " "

    rest = re.sub(r"\(([^()]*)\)", paren, title)
    # "W/ ..." running to the end of the title (bare "with" is too common in real names)
    m = re.search(r"(?:,\s*|\s+)(?:w/|with\s+(?=manual\b))\s*([^()]*)$", rest, re.IGNORECASE)
    if m:
        _apply_hint("w/ " + m.group(1), hints)
        rest = rest[: m.start()]
    hints.title = re.sub(r"\s+", " ", rest).strip(" ,-") or title
    return hints


def _is_hint(part: str) -> bool:
    n = norm(part)
    return (
        bool(re.match(r"(?:w/|with\s)", part, re.IGNORECASE))
        or n in {"nomanual", "nobox"}
        or n in _LOOSE_WORDS | _NEW_WORDS | _CIB_WORDS
    )


def _apply_hint(part: str, hints: TitleHints) -> None:
    n = norm(part)
    wm = re.match(r"(?:w/|with\s)\s*(.*)$", part, re.IGNORECASE)
    if wm:
        _with(_hint_words(wm.group(1), hints), hints)
    elif n == "nomanual":
        hints.has_manual = False
    elif n == "nobox":
        pass  # the default without a box
    elif _hint_words(part, hints):
        hints.extras.append(part)


def _with(what: str, hints: TitleHints) -> None:
    if not what:
        return
    if norm(what) in {"manual", "manuel", "instructions"}:
        hints.has_manual = True
    else:
        hints.extras.append(f"with {what}")


def _cell(row: dict[str, str], mapping: dict[str, str], f: str) -> str:
    col = mapping.get(f)
    return (row.get(col) or "").strip() if col else ""


def analyze(db: Session, user_id: int, rows: list[dict[str, str]], opts: Options) -> list[RowResult]:
    matcher = PlatformMatcher(db)
    if opts.day_first is None:
        date_cols = [opts.mapping[f] for f in ("purchase_date", "sold_date") if opts.mapping.get(f)]
        opts.day_first = detect_day_first(rows, date_cols)
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

        hints = title_hints(cell("title"))
        title = hints.title
        raw_url = cell("pricecharting_url")
        url = normalize_pricecharting_url(raw_url) or "" if raw_url else ""
        if raw_url and not url:
            r.warnings.append("PriceCharting URL ignored (not a pricecharting.com/game/ link)")
        if not title and not url:
            r.errors.append("missing title")
        v["title"] = title

        region_raw = cell("region")
        region = parse_region(region_raw) if region_raw else None
        if region_raw and region is None and norm(region_raw) not in NO_REGION_WORDS:
            r.warnings.append(f"region {region_raw!r} not recognized (use NTSC-U, PAL or NTSC-J)")
        # Distrust links that look like they belong to another game or console; the item is then
        # linked by title search later instead of being priced as the wrong game.
        if url and title and not link_matches_title(title, url):
            r.warnings.append(
                f"PriceCharting link looks like a different game ({url.rsplit('/', 1)[-1]}); ignored"
            )
            url = ""
        platform_raw = cell("platform")
        # A "Consoles" or "Accessories" tab (sheet name as platform) says what the items are;
        # their platform comes from the link or the title instead.
        category_from_platform = _word_lookup(CATEGORY_WORDS, platform_raw) if platform_raw else None
        if category_from_platform and not matcher.match_name(platform_raw):
            platform_raw = ""
        named = matcher.match_name(platform_raw, region, opts.default_region) if platform_raw else None
        linked = matcher.for_url(url)
        if url and named and linked and not any(_same_hardware(named, p) for p in linked):
            r.warnings.append(f"PriceCharting link is for {linked[0].name}, not {named.name}; ignored")
            url = ""
        v["pricecharting_url"] = url or None
        platform = matcher.match(platform_raw, url or None, region, opts.default_region)
        if category_from_platform and not platform_raw:
            in_title = matcher.find_in_text(title, region, opts.default_region)
            # Hardware named in the title wins over the link's console ("Sega Nomad" is priced
            # under Genesis on PriceCharting but is its own platform here).
            platform = in_title or platform
            if platform is None and not default_platform:
                r.errors.append(f"no platform found in {title!r}; pick a default platform")
        if platform is None and platform_raw:
            if default_platform:
                r.warnings.append(f"unknown platform {platform_raw!r}, using {default_platform.name}")
            else:
                r.errors.append(f"unknown platform {platform_raw!r}")
        platform = platform or default_platform
        if platform is None and not r.errors:
            r.errors.append("missing platform")
        elif platform and opts.default_platform_id and not platform_raw:
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
            if not raw and f == "condition":
                parsed = hints.condition
            if not raw and f == "category":
                parsed = category_from_platform
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
                if f != "purchase_price" and v[f] == 0:
                    v[f] = None  # trackers export 0.0 for "not set"
            except ValueError as e:
                r.errors.append(f"{f.replace('_', ' ')}: {e}")
        qty = v.get("quantity") or 1
        if opts.prices_per_row and qty > 1:
            for f in ("purchase_price", "sold_price"):
                if v.get(f) is not None:
                    v[f] = (v[f] / qty).quantize(Decimal("0.01"))
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
        for f, part in (
            ("item_rating", "has_item"),
            ("box_rating", "has_box"),
            ("manual_rating", "has_manual"),
        ):
            try:
                v[f] = parse_rating(cell(f))
            except ValueError as e:
                r.warnings.append(f"{f.replace('_', ' ')}: {e}, ignored")
                v[f] = None
            if v[f] is not None and part not in v:
                v[part] = True  # a rated part is there
        if hints.has_manual is not None and not cell("has_manual"):
            v["has_manual"] = hints.has_manual
        # Sensible component defaults from condition when not given
        v.setdefault("has_item", v["condition"] not in ("box_only", "manual_only"))
        v.setdefault("has_box", v["condition"] in ("cib", "new", "box_only"))
        v.setdefault("has_manual", v["condition"] in ("cib", "new", "manual_only"))
        v.setdefault("has_inserts", False)
        # "Box" in many trackers means game + box without the manual. PriceCharting has no price for
        # that, so value it as loose (with the box noted) rather than as an empty box.
        if v["condition"] == "box_only" and v["has_item"]:
            v["condition"] = Condition.loose.value
            v["has_box"] = True

        upc = re.sub(r"\D", "", cell("upc"))
        v["upc"] = upc if 8 <= len(upc) <= 14 else None
        tags = cell("tags")
        v["tags"] = [t.strip() for t in re.split(r"[;,|]", tags) if t.strip()] if tags else []
        v["region"] = None  # the platform carries the region
        for f in ("grade", "location", "notes"):
            v[f] = cell(f) or None
        if hints.extras:
            extras = "; ".join(hints.extras)
            extras = extras[:1].upper() + extras[1:]
            v["notes"] = f"{v['notes']}\n{extras}" if v["notes"] else extras
        v["acquired_from"] = cell("acquired_from")[:64] or None

        if r.platform_id:
            r.product_id = (
                (url and catalog_by_url.get(url))
                or (v["upc"] and catalog_by_upc.get(v["upc"]))
                or catalog_by_title.get((norm(title), r.platform_id))
                or None
            )
            key = (r.product_id or url or (norm(title), r.platform_id), v["condition"], v["status"])
            if (r.product_id, v["condition"], v["status"]) in owned:
                r.duplicate = True
                r.warnings.append("already in your collection")
            elif key in seen_in_file:
                # A repeated row in a hand-kept sheet is usually a second copy: import it, but say so.
                r.warnings.append("appears more than once in the file")
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
                        "item_rating",
                        "box_rating",
                        "manual_rating",
                        "purchase_price",
                        "purchase_date",
                        "sold_price",
                        "sold_date",
                        "target_price",
                        "location",
                        "acquired_from",
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
