from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    user = "user"


class Category(StrEnum):
    game = "game"
    console = "console"
    pc_big_box = "pc_big_box"
    controller = "controller"
    accessory = "accessory"
    other = "other"


class MediaType(StrEnum):
    cartridge = "cartridge"
    disc = "disc"
    card = "card"
    floppy = "floppy"
    digital = "digital"
    mixed = "mixed"
    none = "none"


class ItemStatus(StrEnum):
    owned = "owned"
    wishlist = "wishlist"
    sold = "sold"


class Condition(StrEnum):
    loose = "loose"
    cib = "cib"
    new = "new"
    graded = "graded"
    box_only = "box_only"
    manual_only = "manual_only"
