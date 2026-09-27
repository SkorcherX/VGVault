from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.security import COOKIE_NAME, create_access_token, hash_password, verify_password
from app.models import User
from app.models.enums import Role
from app.schemas.auth import ChangePassword, Credentials, SetupRequest, SetupStatus, UserOut

router = APIRouter(tags=["auth"])


def _set_session(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_access_token(user.id, user.token_version),
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def _user_count(db: DB) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


@router.get("/setup/status", response_model=SetupStatus)
def setup_status(db: DB):
    return SetupStatus(
        needs_setup=_user_count(db) == 0,
        allow_registration=get_settings().allow_registration,
    )


@router.post("/setup", response_model=UserOut, status_code=201)
def setup(body: SetupRequest, db: DB, response: Response):
    if _user_count(db) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup already completed")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=Role.admin,
    )
    db.add(user)
    db.commit()
    _set_session(response, user)
    return user


@router.post("/auth/login", response_model=UserOut)
def login(body: Credentials, db: DB, response: Response):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    _set_session(response, user)
    return user


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: SetupRequest, db: DB, response: Response):
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username taken")
    user = User(username=body.username, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _set_session(response, user)
    return user


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/auth/change-password", status_code=204)
def change_password(body: ChangePassword, user: CurrentUser, db: DB, response: Response):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    db.commit()
    _set_session(response, user)
