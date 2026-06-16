from __future__ import annotations

import logging
import secrets

import bcrypt
from sqlalchemy.orm import Session

from app.models.entities import AuthSetting

BCRYPT_MAX_PASSWORD_BYTES = 72
FIRST_RUN_PASSWORD_BYTES = 24


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def _validate_bcrypt_password_length(self, password: str) -> bytes:
        password_bytes = password.encode("utf-8")
        if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                "Password is too long for bcrypt hashing. Please choose a password "
                f"that is {BCRYPT_MAX_PASSWORD_BYTES} bytes or fewer when UTF-8 encoded."
            )
        return password_bytes

    def generate_first_run_password(self) -> str:
        password = secrets.token_urlsafe(FIRST_RUN_PASSWORD_BYTES)
        self._validate_bcrypt_password_length(password)
        return password

    def hash_password(self, pw: str) -> str:
        password_bytes = self._validate_bcrypt_password_length(pw)
        return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, pw: str, hashed: str) -> bool:
        password_bytes = self._validate_bcrypt_password_length(pw)
        return bcrypt.checkpw(password_bytes, hashed.encode("utf-8"))

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
