from typing import Literal
from zipfile import BadZipFile

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.models.enums import Category, Condition, ItemStatus
from app.services import autolink, importer
from app.services.workbook import read_workbook

router = APIRouter(prefix="/import", tags=["import"])

MAX_ROWS = 10_000


class ImportBody(BaseModel):
    rows: list[dict[str, str | None]] = Field(max_length=MAX_ROWS)
    mapping: dict[str, str]
    default_status: ItemStatus = ItemStatus.owned
    default_condition: Condition = Condition.loose
    default_platform_id: int | None = None
    default_category: Category = Category.game
    day_first: bool | None = None  # None: auto-detect from the dates
    skip_duplicates: bool = True
    default_region: Literal["NTSC-U", "PAL", "NTSC-J"] = "NTSC-U"
    prices_per_row: bool = False

    def options(self) -> importer.Options:
        unknown = set(self.mapping) - set(importer.FIELDS)
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown fields: {sorted(unknown)}")
        return importer.Options(
            mapping={k: v for k, v in self.mapping.items() if v},
            default_status=self.default_status,
            default_condition=self.default_condition,
            default_platform_id=self.default_platform_id,
            default_category=self.default_category,
            day_first=self.day_first,
            skip_duplicates=self.skip_duplicates,
            default_region=self.default_region,
            prices_per_row=self.prices_per_row,
        )

    def clean_rows(self) -> list[dict[str, str]]:
        return [{k: v or "" for k, v in row.items()} for row in self.rows]


class SuggestBody(BaseModel):
    headers: list[str]
    rows: list[dict[str, str | None]] = Field(default=[], max_length=500)  # sample, for value-based guesses


@router.get("/fields")
def fields(_: CurrentUser):
    return {"fields": importer.FIELDS}


@router.post("/suggest")
def suggest(body: SuggestBody, _: CurrentUser):
    rows = [{k: v or "" for k, v in r.items()} for r in body.rows]
    return importer.suggest_mapping(body.headers, rows)


MAX_WORKBOOK_BYTES = 25 * 1024 * 1024


@router.post("/workbook")
async def workbook(file: UploadFile, _: CurrentUser):
    """Parse an .xlsx into per-sheet headers and rows (the browser then maps and validates)."""
    data = await file.read(MAX_WORKBOOK_BYTES + 1)
    if len(data) > MAX_WORKBOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Workbook is larger than 25 MB")
    try:
        sheets = await run_in_threadpool(read_workbook, data)
    except (InvalidFileException, BadZipFile, KeyError, ValueError) as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Couldn't read that file as an Excel workbook: {e}"
        ) from None
    return {"sheets": sheets}


@router.post("/validate")
def validate(body: ImportBody, db: DB, user: CurrentUser):
    results = importer.analyze(db, user.id, body.clean_rows(), body.options())
    return {
        "rows": [
            {
                "index": r.index,
                "ok": r.ok,
                "errors": r.errors,
                "warnings": r.warnings,
                "title": r.values.get("title"),
                "platform": r.platform_name,
                "condition": r.values.get("condition"),
                "status": r.values.get("status"),
                "quantity": r.values.get("quantity"),
                "purchase_price": r.values.get("purchase_price"),
                "existing_product": r.product_id is not None,
                "duplicate": r.duplicate,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "ok": sum(r.ok for r in results),
            "errors": sum(not r.ok for r in results),
            "duplicates": sum(r.ok and r.duplicate for r in results),
            "new_products": len(
                {
                    (importer.norm(r.values.get("title")), r.platform_id)
                    for r in results
                    if r.ok and not r.product_id
                }
            ),
        },
    }


@router.post("/commit")
def commit(body: ImportBody, db: DB, user: CurrentUser):
    return importer.commit(db, user.id, body.clean_rows(), body.options())


@router.get("/autolink")
def autolink_status(db: DB, user: CurrentUser):
    return {**autolink.state_for(user.id), "unlinked": len(autolink.unlinked_products(db, user.id))}


@router.post("/autolink", status_code=202)
def autolink_start(user: CurrentUser):
    if not autolink.start(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "An auto-link job is already running")
    return {"started": True}


@router.post("/autolink/cancel", status_code=202)
def autolink_cancel(user: CurrentUser):
    if not autolink.cancel(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "No auto-link job of yours is running")
    return {"cancelling": True}
