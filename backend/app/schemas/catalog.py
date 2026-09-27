from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Category, MediaType


class PlatformBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    brand: str
    generation: int | None = None
    era: str | None = None
    media_type: MediaType = MediaType.cartridge
    handheld: bool = False
    region: str = "NTSC-U"
    release_year: int | None = None
    pricecharting_slug: str | None = None


class PlatformOut(PlatformBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PlatformUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    generation: int | None = None
    era: str | None = None
    media_type: MediaType | None = None
    handheld: bool | None = None
    region: str | None = None
    release_year: int | None = None
    pricecharting_slug: str | None = None


class ProductBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    platform_id: int
    category: Category = Category.game
    region: str | None = None
    genre: str | None = None
    release_date: date | None = None
    upc: str | None = None
    pricecharting_id: str | None = None
    pricecharting_url: str | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    title: str | None = None
    platform_id: int | None = None
    category: Category | None = None
    region: str | None = None
    genre: str | None = None
    release_date: date | None = None
    upc: str | None = None
    pricecharting_id: str | None = None
    pricecharting_url: str | None = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: PlatformOut
    has_image: bool = False
    last_priced_at: datetime | None = None
