from __future__ import annotations
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.entities import AbsCacheBook
class DuplicateService:
    def __init__(self, db:Session): self.db=db
    def find(self, metadata:dict)->list[dict]:
        matches=[]; asin=(metadata.get('asin') or '').strip(); title=(metadata.get('title') or metadata.get('album') or '').strip().lower(); author=(metadata.get('author') or '').strip().lower()
        if asin:
            for b in self.db.query(AbsCacheBook).filter(func.lower(AbsCacheBook.asin)==asin.lower()).all(): matches.append({'match_type':'gold_asin','abs_book_id':b.id,'title':b.title,'author':b.author,'asin':b.asin,'duration':b.duration,'chapters':b.chapters})
        if title and author:
            for b in self.db.query(AbsCacheBook).filter(func.lower(AbsCacheBook.title)==title, func.lower(AbsCacheBook.author)==author).all(): matches.append({'match_type':'title_author','abs_book_id':b.id,'title':b.title,'author':b.author,'asin':b.asin,'duration':b.duration,'chapters':b.chapters})
        return matches
