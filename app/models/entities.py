from __future__ import annotations
import enum, uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class BookStatus(str, enum.Enum):
    incoming='incoming'; staging='staging'; needs_review='needs_review'; ready='ready'; converting='converting'; failed='failed'; ready_for_library='ready_for_library'; completed='completed'
class JobStatus(str, enum.Enum):
    queued='queued'; scanning='scanning'; needs_review='needs_review'; ready='ready'; running='running'; paused='paused'; completed='completed'; completed_waiting_library_move='completed_waiting_library_move'; failed='failed'; cancelled='cancelled'

class AppSetting(Base):
    __tablename__='app_settings'
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class AuthSetting(Base):
    __tablename__='auth_settings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    require_password_every_visit: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_persistent_session: Mapped[bool] = mapped_column(Boolean, default=True)
class AbsCacheBook(Base):
    __tablename__='abs_cache_books'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str|None] = mapped_column(String(500)); subtitle: Mapped[str|None] = mapped_column(String(500)); author: Mapped[str|None] = mapped_column(String(500)); narrator: Mapped[str|None] = mapped_column(String(500)); series: Mapped[str|None] = mapped_column(String(500)); series_sequence: Mapped[str|None] = mapped_column(String(80)); description: Mapped[str|None] = mapped_column(Text); asin: Mapped[str|None] = mapped_column(String(80), index=True); cover: Mapped[str|None] = mapped_column(Text); chapters: Mapped[list] = mapped_column(JSON, default=list); duration: Mapped[float|None] = mapped_column(Integer); raw: Mapped[dict] = mapped_column(JSON, default=dict); updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
class Book(Base):
    __tablename__='books'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[BookStatus] = mapped_column(Enum(BookStatus), default=BookStatus.staging, index=True)
    source_path: Mapped[str] = mapped_column(Text); book_type: Mapped[str] = mapped_column(String(32), default='single_file')
    failure_reason: Mapped[str|None] = mapped_column(Text); validation_issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow); updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata: Mapped['BookMetadata'] = relationship(back_populates='book', uselist=False, cascade='all, delete-orphan')
class BookFile(Base):
    __tablename__='book_files'
    id: Mapped[int] = mapped_column(Integer, primary_key=True); book_id: Mapped[str] = mapped_column(ForeignKey('books.id'))
    path: Mapped[str] = mapped_column(Text); size_bytes: Mapped[int] = mapped_column(Integer, default=0); role: Mapped[str] = mapped_column(String(40), default='source')
class BookMetadata(Base):
    __tablename__='book_metadata'
    book_id: Mapped[str] = mapped_column(ForeignKey('books.id'), primary_key=True)
    title: Mapped[str|None] = mapped_column(String(500)); subtitle: Mapped[str|None] = mapped_column(String(500)); author: Mapped[str|None] = mapped_column(String(500)); narrator: Mapped[str|None] = mapped_column(String(500)); series: Mapped[str|None] = mapped_column(String(500)); series_sequence: Mapped[str|None] = mapped_column(String(80)); description: Mapped[str|None] = mapped_column(Text); asin: Mapped[str|None] = mapped_column(String(80)); cover: Mapped[str|None] = mapped_column(Text); chapters: Mapped[list] = mapped_column(JSON, default=list); duration: Mapped[float|None] = mapped_column(Integer); target_bitrate: Mapped[int|None] = mapped_column(Integer); target_channels: Mapped[int|None] = mapped_column(Integer); dramatic_audio: Mapped[bool] = mapped_column(Boolean, default=False); manual_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    book: Mapped[Book] = relationship(back_populates='metadata')
class Duplicate(Base):
    __tablename__='duplicates'; id: Mapped[int] = mapped_column(Integer, primary_key=True); book_id: Mapped[str] = mapped_column(ForeignKey('books.id')); abs_book_id: Mapped[str] = mapped_column(ForeignKey('abs_cache_books.id')); match_type: Mapped[str] = mapped_column(String(32)); __table_args__=(UniqueConstraint('book_id','abs_book_id','match_type'),)
class ConversionJob(Base):
    __tablename__='conversion_jobs'; id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued); dry_run: Mapped[bool]=mapped_column(Boolean, default=False); move_to_library: Mapped[bool]=mapped_column(Boolean, default=False); progress_percent: Mapped[int]=mapped_column(Integer, default=0); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow); started_at: Mapped[datetime|None]=mapped_column(DateTime); ended_at: Mapped[datetime|None]=mapped_column(DateTime); failure_reason: Mapped[str|None]=mapped_column(Text)
class ConversionJobBook(Base):
    __tablename__='conversion_job_books'; id: Mapped[int]=mapped_column(Integer, primary_key=True); job_id: Mapped[str]=mapped_column(ForeignKey('conversion_jobs.id')); book_id: Mapped[str]=mapped_column(ForeignKey('books.id')); status: Mapped[str]=mapped_column(String(40), default='queued')
class ConversionEvent(Base):
    __tablename__='conversion_events'; id: Mapped[int]=mapped_column(Integer, primary_key=True); job_id: Mapped[str]=mapped_column(ForeignKey('conversion_jobs.id'), index=True); book_id: Mapped[str|None]=mapped_column(String(36)); event: Mapped[str]=mapped_column(String(80)); stage: Mapped[str|None]=mapped_column(String(80)); percent: Mapped[int|None]=mapped_column(Integer); message: Mapped[str|None]=mapped_column(Text); payload: Mapped[dict]=mapped_column(JSON, default=dict); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
class ConversionStats(Base):
    __tablename__='conversion_stats'; id: Mapped[int]=mapped_column(Integer, primary_key=True); job_id: Mapped[str]=mapped_column(ForeignKey('conversion_jobs.id')); book_id: Mapped[str]=mapped_column(ForeignKey('books.id')); payload: Mapped[dict]=mapped_column(JSON, default=dict); status: Mapped[str]=mapped_column(String(40)); failure_reason: Mapped[str|None]=mapped_column(Text)
class FileMove(Base):
    __tablename__='file_moves'; id: Mapped[int]=mapped_column(Integer, primary_key=True); book_id: Mapped[str|None]=mapped_column(String(36)); source_path: Mapped[str]=mapped_column(Text); destination_path: Mapped[str]=mapped_column(Text); reason: Mapped[str]=mapped_column(String(80)); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
class DeletionJob(Base):
    __tablename__='deletion_jobs'; id: Mapped[str]=mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4())); paths: Mapped[list]=mapped_column(JSON, default=list); confirmed: Mapped[bool]=mapped_column(Boolean, default=False); status: Mapped[str]=mapped_column(String(40), default='pending')
class MetadataBackup(Base):
    __tablename__='metadata_backups'; id: Mapped[int]=mapped_column(Integer, primary_key=True); book_id: Mapped[str]=mapped_column(ForeignKey('books.id')); payload: Mapped[dict]=mapped_column(JSON, default=dict); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
