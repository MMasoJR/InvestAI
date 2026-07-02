"""Acesso a dados de usuários — isola o ORM dos routers."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.db_models import User
from backend.app.services.auth import hash_password, verify_password


class UserStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self.db.get(User, user_id)

    def create(self, email: str, password: str) -> User:
        user = User(email=email.lower().strip(), hashed_password=hash_password(password))
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> Optional[User]:
        user = self.get_by_email(email.lower().strip())
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user
