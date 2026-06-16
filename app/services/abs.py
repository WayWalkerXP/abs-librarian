from __future__ import annotations
from datetime import datetime
import httpx
from sqlalchemy.orm import Session
from app.models.entities import AbsCacheBook
class AbsClient:
    def __init__(self, base_url:str, token:str): self.base_url=base_url.rstrip('/'); self.token=token
    def fetch_library_items(self, library_id:str)->list[dict]:
        headers={'Authorization': f'Bearer {self.token}'} if self.token else {}
        r=httpx.get(f'{self.base_url}/api/libraries/{library_id}/items', headers=headers, timeout=20); r.raise_for_status()
        data=r.json(); return data.get('results') or data.get('items') or []
class AbsCacheService:
    def __init__(self, db:Session): self.db=db; self.last_error=None
    def refresh(self, client:AbsClient, library_id:str)->bool:
        try: items=client.fetch_library_items(library_id)
        except Exception as exc: self.last_error=str(exc); return False
        for item in items:
            media=item.get('media') or {}; meta=media.get('metadata') or item.get('metadata') or {}
            book=AbsCacheBook(id=str(item.get('id')), title=meta.get('title'), subtitle=meta.get('subtitle'), author=', '.join(a.get('name','') for a in meta.get('authors',[]) if isinstance(a,dict)) or meta.get('authorName') or meta.get('author'), narrator=meta.get('narratorName') or meta.get('narrator'), series=(meta.get('series') or [{}])[0].get('name') if isinstance(meta.get('series'),list) and meta.get('series') else meta.get('seriesName'), series_sequence=(meta.get('series') or [{}])[0].get('sequence') if isinstance(meta.get('series'),list) and meta.get('series') else None, description=meta.get('description'), asin=meta.get('asin'), cover=item.get('mediaCover'), chapters=media.get('chapters') or [], duration=media.get('duration'), raw=item, updated_at=datetime.utcnow())
            self.db.merge(book)
        self.db.commit(); self.last_error=None; return True
    def status(self): return {'reachable': self.last_error is None, 'last_error': self.last_error, 'cached_books': self.db.query(AbsCacheBook).count()}
