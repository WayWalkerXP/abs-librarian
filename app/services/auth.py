from __future__ import annotations
import logging, secrets
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.models.entities import AuthSetting
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
class AuthService:
    def __init__(self, db: Session): self.db=db
    def hash_password(self,pw:str)->str: return pwd_context.hash(pw)
    def verify_password(self,pw:str, hashed:str)->bool: return pwd_context.verify(pw, hashed)
    def ensure_first_run_password(self)->str|None:
        existing=self.db.get(AuthSetting,1)
        if existing: return None
        password=secrets.token_urlsafe(18)
        self.db.add(AuthSetting(id=1,password_hash=self.hash_password(password),must_change_password=True))
        self.db.commit(); logging.warning('ABS Librarian initial password: %s', password); print(f'ABS Librarian initial password: {password}')
        return password
    def authenticate(self,password:str)->bool:
        auth=self.db.get(AuthSetting,1); return bool(auth and self.verify_password(password,auth.password_hash))
    def change_password(self,new_password:str):
        auth=self.db.get(AuthSetting,1) or AuthSetting(id=1,password_hash='')
        auth.password_hash=self.hash_password(new_password); auth.must_change_password=False; self.db.merge(auth); self.db.commit()
