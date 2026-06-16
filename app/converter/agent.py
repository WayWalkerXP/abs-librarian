from __future__ import annotations
import json, sys, time
from pathlib import Path
from app.services.metadata import validate_conversion_settings

def emit(payload:dict): print(json.dumps(payload, default=str), flush=True)
def run_agent(input_stream=sys.stdin)->int:
    payload=json.load(input_stream); job_id=payload.get('job_id','agent-job'); dry=payload.get('dry_run',False); books=payload.get('books',[])
    emit({'event':'job_started','job_id':job_id,'stage':'starting','percent':0,'message':'Agent conversion started'})
    failures=0
    for book in books:
        bid=book.get('book_id') or book.get('id'); meta=book.get('metadata') or {}; issues=validate_conversion_settings(meta.get('target_bitrate') or book.get('target_bitrate'), meta.get('target_channels') or book.get('target_channels'))
        if issues:
            failures+=1; emit({'event':'book_failed','job_id':job_id,'book_id':bid,'stage':'validation','percent':0,'message':'; '.join(issues)}); continue
        emit({'event':'book_progress','job_id':job_id,'book_id':bid,'stage':'encoding','percent':42,'message':'Encoding current book'})
        time.sleep(0.01)
        stats={'source_file_size':0,'output_file_size':0,'size_saved':0,'target_bitrate':meta.get('target_bitrate'),'target_channels':meta.get('target_channels'),'status':'dry_run' if dry else 'completed'}
        emit({'event':'book_completed','job_id':job_id,'book_id':bid,'stage':'completed','percent':100,'message':'Dry run complete' if dry else 'Conversion complete','stats':stats})
    emit({'event':'job_completed' if failures==0 else 'job_failed','job_id':job_id,'stage':'finished','percent':100,'message':'Agent conversion finished'})
    return 0 if failures==0 else 2
