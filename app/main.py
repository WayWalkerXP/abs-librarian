from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.db.session import Base, SessionLocal, engine
from app.models import entities  # noqa
from app.services.auth import AuthService


WORKFLOW_PAGES = {
    "/dashboard": ("Dashboard", "Overview of audiobook workflow status and key actions."),
    "/incoming": ("Incoming / Scan", "Scan incoming audiobook sources and prepare them for staging."),
    "/staging": ("Staging Review", "Review staged books, metadata, duplicates, and conversion settings."),
    "/books": ("Book Detail", "Inspect and edit details for a selected staged book."),
    "/book-detail": ("Book Detail", "Inspect and edit details for a selected staged book."),
    "/jobs": ("Jobs", "Monitor conversion jobs and worker progress."),
    "/ready-for-library": ("Ready for Library", "Review converted audiobooks that are ready to move into the library."),
    "/settings": ("Settings", "Configure ABS Librarian settings."),
}


def render_page(title: str, description: str, *, placeholder: bool = True) -> str:
    placeholder_notice = (
        "<p class=\"notice\">This feature is not implemented yet. "
        "This temporary placeholder confirms the route is wired for local development.</p>"
        if placeholder
        else ""
    )
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{title} - ABS Librarian</title>
        <style>
          :root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; }}
          body {{ margin: 0; background: #101418; color: #f4f7fb; }}
          main {{ max-width: 960px; margin: 0 auto; padding: 48px 24px; }}
          .panel {{ background: #18212b; border: 1px solid #2d3a48; border-radius: 18px; padding: 32px; }}
          h1 {{ margin: 0 0 12px; font-size: clamp(2rem, 5vw, 3.5rem); }}
          p {{ color: #cbd5e1; font-size: 1.1rem; line-height: 1.6; }}
          .notice {{ background: #263241; border-radius: 12px; padding: 16px; color: #dbeafe; }}
          a {{ color: #101418; background: #8bd3ff; display: inline-block; margin-top: 18px; padding: 12px 16px; border-radius: 10px; text-decoration: none; font-weight: 700; }}
        </style>
      </head>
      <body>
        <main>
          <section class="panel">
            <h1>{title}</h1>
            <p>{description}</p>
            {placeholder_notice}
            <a href="/">Back to landing page</a>
          </section>
        </main>
      </body>
    </html>
    """


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
              .card { background: #18212b; border: 1px solid #2d3a48; border-radius: 14px; padding: 16px; color: #dbeafe; display: block; min-height: 56px; }
              .card:hover, .card:focus { border-color: #8bd3ff; outline: none; }
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
                  <a href="/settings" class="secondary">View settings</a>
                </nav>
              </section>
              <section class="grid" aria-label="Planned workflow areas">
                <a class="card" href="/dashboard">Dashboard</a>
                <a class="card" href="/incoming">Incoming / Scan</a>
                <a class="card" href="/staging">Staging Review</a>
                <a class="card" href="/books">Book Detail</a>
                <a class="card" href="/jobs">Jobs</a>
                <a class="card" href="/ready-for-library">Ready for Library</a>
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

    @app.get(
        "/{page_path:path}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def workflow_page(page_path: str) -> str:
        route = f"/{page_path}"
        if route not in WORKFLOW_PAGES:
            raise HTTPException(status_code=404, detail="Not found")
        title, description = WORKFLOW_PAGES[route]
        return render_page(title, description)

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
