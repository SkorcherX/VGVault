from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import DB, AdminUser
from app.services import backups, scheduler

router = APIRouter(prefix="/admin/backups", tags=["admin"])


class BackupFile(BaseModel):
    name: str
    size: int
    created_at: datetime


class BackupStatus(BaseModel):
    supported: bool
    settings: backups.BackupSettings
    next_run_at: datetime | None
    directory: str
    backups: list[BackupFile]


@router.get("", response_model=BackupStatus)
def status_(db: DB, _: AdminUser):
    return BackupStatus(
        supported=backups.supported(),
        settings=backups.get_backup_settings(db),
        next_run_at=scheduler.next_run_time(scheduler.BACKUP_JOB_ID),
        directory=str(backups.backup_dir()),
        backups=backups.list_backups(),
    )


@router.put("/settings", response_model=backups.BackupSettings)
def update_settings(body: backups.BackupSettings, db: DB, _: AdminUser):
    backups.save_backup_settings(db, body)
    scheduler.apply_backup(body)
    return body


@router.post("", response_model=BackupFile, status_code=201)
def create(db: DB, _: AdminUser):
    try:
        path = backups.create_backup(backups.get_backup_settings(db).keep)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return next(b for b in backups.list_backups() if b["name"] == path.name)


@router.get("/{name}")
def download(name: str, _: AdminUser):
    path = backups.resolve(name)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found")
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=name)


@router.delete("/{name}", status_code=204)
def delete(name: str, _: AdminUser):
    path = backups.resolve(name)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found")
    path.unlink()
