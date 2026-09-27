from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import COOKIE_NAME, decode_access_token
from app.models import User

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> User:
    payload = decode_access_token(token) if token else None
    if payload:
        user = db.get(User, int(payload["sub"]))
        if user and user.is_active and user.token_version == payload.get("ver"):
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
