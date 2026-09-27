from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, AdminUser, CurrentUser
from app.models import CollectionItem, Platform, Product
from app.models.enums import Category
from app.schemas.catalog import (
    PlatformBase,
    PlatformOut,
    PlatformUpdate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
)

router = APIRouter(tags=["catalog"])


def _commit(db: DB, conflict_msg: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, conflict_msg) from None


# --- Platforms ---------------------------------------------------------------


@router.get("/platforms", response_model=list[PlatformOut])
def list_platforms(db: DB, _: CurrentUser, brand: str | None = None):
    q = select(Platform).order_by(Platform.brand, Platform.release_year, Platform.name)
    if brand:
        q = q.where(Platform.brand == brand)
    return db.scalars(q).all()


@router.post("/platforms", response_model=PlatformOut, status_code=201)
def create_platform(body: PlatformBase, db: DB, _: AdminUser):
    platform = Platform(**body.model_dump())
    db.add(platform)
    _commit(db, "Platform slug already exists")
    return platform


@router.patch("/platforms/{platform_id}", response_model=PlatformOut)
def update_platform(platform_id: int, body: PlatformUpdate, db: DB, _: AdminUser):
    platform = db.get(Platform, platform_id)
    if not platform:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(platform, key, value)
    db.commit()
    return platform


@router.delete("/platforms/{platform_id}", status_code=204)
def delete_platform(platform_id: int, db: DB, _: AdminUser):
    platform = db.get(Platform, platform_id)
    if not platform:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    if db.scalar(select(exists().where(Product.platform_id == platform_id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Platform has products")
    db.delete(platform)
    db.commit()


# --- Products ----------------------------------------------------------------


@router.get("/products", response_model=list[ProductOut])
def search_products(
    db: DB,
    _: CurrentUser,
    q: str | None = None,
    platform_id: int | None = None,
    category: Category | None = None,
    upc: str | None = None,
    limit: int = Query(50, le=200),
):
    stmt = select(Product).order_by(Product.title).limit(limit)
    if upc:
        stmt = stmt.where(Product.upc == upc)
    if q:
        stmt = stmt.where(Product.title.ilike(f"%{q}%"))
    if platform_id:
        stmt = stmt.where(Product.platform_id == platform_id)
    if category:
        stmt = stmt.where(Product.category == category)
    return db.scalars(stmt).all()


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: DB, _: CurrentUser):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, db: DB, _: CurrentUser):
    if not db.get(Platform, body.platform_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown platform")
    product = Product(**body.model_dump())
    db.add(product)
    _commit(db, "Product with this PriceCharting ID already exists")
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductUpdate, db: DB, _: AdminUser):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    _commit(db, "Product with this PriceCharting ID already exists")
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: DB, _: AdminUser):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if db.scalar(select(exists().where(CollectionItem.product_id == product_id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Product is in a collection")
    db.delete(product)
    db.commit()
