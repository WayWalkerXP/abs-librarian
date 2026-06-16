from __future__ import annotations
import time
from app.db.session import SessionLocal
from app.models.entities import ConversionJob, JobStatus
if __name__ == '__main__':
    print('ABS Librarian worker started')
    while True:
        db=SessionLocal()
        try:
            for job in db.query(ConversionJob).filter_by(status=JobStatus.running).all():
                print(f'resumable job observed: {job.id}')
        finally: db.close()
        time.sleep(10)
