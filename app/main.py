from __future__ import annotations
from fastapi import FastAPI
from app.api.routes import router
from app.db.session import Base, SessionLocal, engine
from app.models import entities  # noqa
from app.services.auth import AuthService

def create_app() -> FastAPI:
    app=FastAPI(title='ABS Librarian')
    app.include_router(router, prefix='/api')
    @app.on_event('startup')
    def startup():
        Base.metadata.create_all(bind=engine)
        db=SessionLocal()
        try: AuthService(db).ensure_first_run_password()
        finally: db.close()
    return app
app=create_app()
