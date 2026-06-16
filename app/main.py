from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.db.session import Base, SessionLocal, engine
from app.models import entities  # noqa
from app.services.auth import AuthService


def create_app() -> FastAPI:
    app = FastAPI(title="ABS Librarian")
    app.include_router(router, prefix="/api")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root() -> str:
        return """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>ABS Librarian</title>
            <style>
              :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
              body { margin: 0; background: #101418; color: #f4f7fb; }
              main { max-width: 960px; margin: 0 auto; padding: 48px 24px; }
              .hero { background: #18212b; border: 1px solid #2d3a48; border-radius: 18px; padding: 32px; }
              h1 { margin: 0 0 12px; font-size: clamp(2rem, 5vw, 3.5rem); }
              p { color: #cbd5e1; font-size: 1.1rem; line-height: 1.6; }
              nav { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
              a { color: #101418; background: #8bd3ff; padding: 12px 16px; border-radius: 10px; text-decoration: none; font-weight: 700; }
              a.secondary { color: #f4f7fb; background: #263241; }
              .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 24px; }
              .card { background: #18212b; border: 1px solid #2d3a48; border-radius: 14px; padding: 16px; color: #dbeafe; }
            </style>
          </head>
          <body>
            <main>
              <section class="hero">
                <h1>ABS Librarian</h1>
                <p>Audiobookshelf conversion workflow dashboard. The FastAPI backend is running and ready for local development.</p>
                <nav aria-label="Application links">
                  <a href="/docs">Open API docs</a>
                  <a href="/health" class="secondary">Check health</a>
                  <a href="/api/settings" class="secondary">View settings API</a>
                </nav>
              </section>
              <section class="grid" aria-label="Planned workflow areas">
                <div class="card">Dashboard</div>
                <div class="card">Incoming / Scan</div>
                <div class="card">Staging Review</div>
                <div class="card">Book Detail</div>
                <div class="card">Jobs</div>
                <div class="card">Ready for Library</div>
              </section>
            </main>
          </body>
        </html>
        """

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.on_event("startup")
    def startup():
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            AuthService(db).ensure_first_run_password()
        finally:
            db.close()

    return app


app = create_app()
