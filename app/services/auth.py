from __future__ import annotations

import logging
import secrets

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models.entities import AuthSetting

BCRYPT_MAX_PASSWORD_BYTES = 72
FIRST_RUN_PASSWORD_BYTES = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def _validate_bcrypt_password_length(self, password: str) -> None:
        password_length = len(password.encode("utf-8"))
        if password_length > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                "Password is too long for bcrypt hashing. Please choose a password "
                f"that is {BCRYPT_MAX_PASSWORD_BYTES} bytes or fewer when UTF-8 encoded."
            )

    def generate_first_run_password(self) -> str:
        password = secrets.token_urlsafe(FIRST_RUN_PASSWORD_BYTES)
        self._validate_bcrypt_password_length(password)
        return password

    def hash_password(self, pw: str) -> str:
        self._validate_bcrypt_password_length(pw)
        return pwd_context.hash(pw)

    def verify_password(self, pw: str, hashed: str) -> bool:
        self._validate_bcrypt_password_length(pw)
        return pwd_context.verify(pw, hashed)

    def ensure_first_run_password(self) -> str | None:
        existing = self.db.get(AuthSetting, 1)
        if existing:
            return None
        password = self.generate_first_run_password()
        self.db.add(
            AuthSetting(
                id=1,
                password_hash=self.hash_password(password),
                must_change_password=True,
            )
        )
        self.db.commit()
        logging.warning("ABS Librarian initial password: %s", password)
        print(f"ABS Librarian initial password: {password}")
        return password

    def authenticate(self, password: str) -> bool:
        auth = self.db.get(AuthSetting, 1)
        return bool(auth and self.verify_password(password, auth.password_hash))

    def change_password(self, new_password: str):
        auth = self.db.get(AuthSetting, 1) or AuthSetting(id=1, password_hash="")
        auth.password_hash = self.hash_password(new_password)
        auth.must_change_password = False
        self.db.merge(auth)
        self.db.commit()
