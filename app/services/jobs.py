from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.entities import Book, BookStatus, ConversionEvent, ConversionJob, ConversionJobBook, JobStatus
from app.services.metadata import validate_conversion_settings
class ConversionJobService:
    def __init__(self, db:Session): self.db=db
    def launch(self, book_ids:list[str], dry_run:bool=False, move_to_library:bool=False)->ConversionJob:
        job=ConversionJob(dry_run=dry_run, move_to_library=move_to_library, status=JobStatus.queued); self.db.add(job); self.db.flush()
        for bid in book_ids: self.db.add(ConversionJobBook(job_id=job.id, book_id=bid))
        self.db.commit(); return job
    def record_event(self, payload:dict):
        self.db.add(ConversionEvent(job_id=payload['job_id'], book_id=payload.get('book_id'), event=payload.get('event','log'), stage=payload.get('stage'), percent=payload.get('percent'), message=payload.get('message'), payload=payload)); self.db.commit()
    def mark_running(self, job:ConversionJob): job.status=JobStatus.running; job.started_at=datetime.utcnow(); self.db.commit()
    def validate_book_ready(self, book:Book)->list[str]:
        if not book.book_metadata: return ['missing metadata']
        return validate_conversion_settings(book.book_metadata.target_bitrate, book.book_metadata.target_channels)
