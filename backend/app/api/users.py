from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser
from app.core.security import hash_password
from app.models import User
from app.models.enums import Role
from app.schemas.auth import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get(db: DB, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _other_active_admins(db: DB, user_id: int) -> int:
    q = select(func.count()).where(User.role == Role.admin, User.is_active, User.id != user_id)
    return db.scalar(q) or 0


@router.get("", response_model=list[UserOut])
def list_users(db: DB, _: AdminUser):
    return db.scalars(select(User).order_by(User.username)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DB, _: AdminUser):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username taken")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: DB, _: AdminUser):
    user = _get(db, user_id)
    demoting = (body.role and body.role != Role.admin) or body.is_active is False
    if user.is_admin and demoting and _other_active_admins(db, user.id) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot remove the last active admin")
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            user.token_version += 1
    if body.password:
        user.password_hash = hash_password(body.password)
        user.token_version += 1
    db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: DB, admin: AdminUser):
    user = _get(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    db.delete(user)
    db.commit()
