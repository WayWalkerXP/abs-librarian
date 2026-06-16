from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import Book, ConversionEvent, ConversionJob
from app.services.abs import AbsCacheService, AbsClient
from app.services.auth import AuthService
from app.services.duplicates import DuplicateService
from app.services.jobs import ConversionJobService
from app.services.scanner import ScannerService
from app.services.settings import SettingsService
router=APIRouter()
@router.post('/auth/login')
def login(payload:dict, db:Session=Depends(get_db)):
    if not AuthService(db).authenticate(payload.get('password','')): raise HTTPException(401,'invalid password')
    return {'ok':True}
@router.post('/auth/change-password')
def change_password(payload:dict, db:Session=Depends(get_db)): AuthService(db).change_password(payload['password']); return {'ok':True}
@router.get('/settings')
def get_settings_api(db:Session=Depends(get_db)): return SettingsService(db).get_all()
@router.put('/settings/{key}')
def put_setting(key:str,payload:dict,db:Session=Depends(get_db)): SettingsService(db).set(key,payload.get('value')); return {'ok':True}
@router.post('/abs/refresh')
def abs_refresh(db:Session=Depends(get_db)):
    s=SettingsService(db).get_all(); ok=AbsCacheService(db).refresh(AbsClient(s.get('abs_base_url',''),s.get('abs_api_token','')),s.get('abs_library_id','')); return {'ok':ok}
@router.get('/abs/status')
def abs_status(db:Session=Depends(get_db)): return AbsCacheService(db).status()
@router.post('/scan/incoming')
def scan(db:Session=Depends(get_db)):
    s=SettingsService(db).get_all(); return [{'id':b.id,'source_path':b.source_path,'book_type':b.book_type,'status':b.status.value} for b in ScannerService(db).scan_incoming(Path(s['incoming_dir']))]
@router.get('/staging/books')
def staging(db:Session=Depends(get_db)): return db.query(Book).all()
@router.get('/books/{book_id}')
def book_detail(book_id:str,db:Session=Depends(get_db)):
    b=db.get(Book,book_id); 
    if not b: raise HTTPException(404,'book not found')
    return b
@router.put('/books/{book_id}/metadata')
def update_metadata(book_id:str,payload:dict,db:Session=Depends(get_db)):
    b=db.get(Book,book_id); 
    if not b or not b.book_metadata: raise HTTPException(404,'book not found')
    for k,v in payload.items():
        if hasattr(b.book_metadata,k): setattr(b.book_metadata,k,v)
    db.commit(); return {'ok':True}
@router.get('/books/{book_id}/duplicates')
def duplicates(book_id:str,db:Session=Depends(get_db)):
    b=db.get(Book,book_id); 
    if not b or not b.book_metadata: raise HTTPException(404,'book not found')
    return DuplicateService(db).find(b.book_metadata.__dict__)
@router.post('/jobs')
def launch_job(payload:dict,db:Session=Depends(get_db)):
    job=ConversionJobService(db).launch(payload.get('book_ids',[]), payload.get('dry_run',False), payload.get('move_to_library',False)); return {'id':job.id,'status':job.status.value}
@router.get('/jobs')
def jobs(db:Session=Depends(get_db)): return db.query(ConversionJob).order_by(ConversionJob.created_at.desc()).all()
@router.get('/jobs/{job_id}/events')
def job_events(job_id:str,db:Session=Depends(get_db)): return db.query(ConversionEvent).filter_by(job_id=job_id).all()
@router.post('/failed/{book_id}/retry')
def retry_failed(book_id:str,db:Session=Depends(get_db)):
    b=db.get(Book,book_id); b.status='staging'; b.failure_reason=None; db.commit(); return {'ok':True}
@router.get('/archive/converted')
def archive(db:Session=Depends(get_db)): return {'paths':[str(p) for p in Path(SettingsService(db).get_all()['converted_dir']).rglob('*') if p.is_file()]}
