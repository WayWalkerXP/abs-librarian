from __future__ import annotations
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.entities import Book, BookFile, BookMetadata, BookStatus
AUDIO_EXT={'.m4b','.mp3','.m4a','.aac','.flac','.ogg','.wav'}
class ScannerService:
    def __init__(self, db:Session): self.db=db
    def scan_incoming(self, incoming_dir:Path)->list[Book]:
        books=[]
        for p in incoming_dir.iterdir() if incoming_dir.exists() else []:
            if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                b=Book(source_path=str(p), book_type='single_file', status=BookStatus.staging); self.db.add(b); self.db.flush(); self.db.add(BookFile(book_id=b.id,path=str(p),size_bytes=p.stat().st_size)); self.db.add(BookMetadata(book_id=b.id,title=p.stem,target_bitrate=64,target_channels=1)); books.append(b)
            elif p.is_dir() and any(x.suffix.lower() in AUDIO_EXT for x in p.rglob('*')):
                b=Book(source_path=str(p), book_type='folder', status=BookStatus.staging); self.db.add(b); self.db.flush(); self.db.add(BookMetadata(book_id=b.id,title=p.name,target_bitrate=64,target_channels=1)); books.append(b)
        self.db.commit(); return books
