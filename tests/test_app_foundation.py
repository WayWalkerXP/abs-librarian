from io import StringIO
from pathlib import Path
import json
import pytest
sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.converter.agent import run_agent
from app.db.session import Base
from app.models.entities import AbsCacheBook, Book, BookMetadata, BookStatus
from app.services.auth import AuthService, BCRYPT_MAX_PASSWORD_BYTES
from app.services.duplicates import DuplicateService
from app.services.filesystem import FilesystemService
from app.services.jobs import ConversionJobService
from app.services.library import render_output_path
from app.services.metadata import resolve_metadata, validate_conversion_settings
from app.services.settings import SettingsService

def db_session():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    return Session()

def test_settings_persistence():
    db=db_session(); svc=SettingsService(db); svc.set('incoming_dir','/tmp/incoming'); assert svc.get_all()['incoming_dir']=='/tmp/incoming'

def test_password_hashing_auth():
    db=db_session(); svc=AuthService(db); svc.change_password('secret'); assert svc.authenticate('secret'); assert not svc.authenticate('bad')



def test_first_run_password_generation_is_bcrypt_safe():
    db = db_session()
    svc = AuthService(db)

    password = svc.generate_first_run_password()

    assert 24 <= len(password) <= 32
    assert len(password.encode("utf-8")) <= BCRYPT_MAX_PASSWORD_BYTES


def test_first_run_password_can_be_hashed_and_stored():
    db = db_session()
    svc = AuthService(db)

    password = svc.ensure_first_run_password()

    assert password is not None
    assert len(password.encode("utf-8")) <= BCRYPT_MAX_PASSWORD_BYTES
    assert svc.authenticate(password)


def test_too_long_password_fails_with_clear_error():
    db = db_session()
    svc = AuthService(db)
    too_long_password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValueError, match="too long for bcrypt"):
        svc.hash_password(too_long_password)

def test_metadata_priority_resolution():
    assert resolve_metadata({'title':'embedded'}, {'title':'yaml'}, {'title':'abs'}, {'title':'manual'})['title']=='manual'

def test_invalid_bitrate_channel_blocking():
    assert validate_conversion_settings(24,3)
    assert validate_conversion_settings(64,1)==[]

def test_duplicate_detection():
    db=db_session(); db.add(AbsCacheBook(id='1',title='Book',author='Author',asin='ASIN1',chapters=[],raw={})); db.commit()
    matches=DuplicateService(db).find({'title':'Book','author':'Author','asin':'ASIN1'})
    assert {m['match_type'] for m in matches} >= {'gold_asin','title_author'}

def test_job_state_transitions():
    db=db_session(); job=ConversionJobService(db).launch(['book1'], dry_run=True); assert job.status.value=='queued'; ConversionJobService(db).mark_running(job); assert job.status.value=='running'

def test_failed_conversion_handling_moves_not_deletes(tmp_path):
    src=tmp_path/'book.mp3'; src.write_text('x'); failed=tmp_path/'failed'; FilesystemService().archive_failed(src, failed); assert (failed/'book.mp3').exists(); assert not src.exists()

def test_output_path_template_rendering_series_fallback():
    assert render_output_path('{author}/{series}/{series_sequence} - {album}', {'author':'A','album':'B'}) == Path('A/B')

def test_converter_agent_json_event_parsing(capsys):
    rc=run_agent(StringIO(json.dumps({'job_id':'j','dry_run':True,'books':[{'book_id':'b','metadata':{'target_bitrate':64,'target_channels':1}}]})))
    assert rc==0
    events=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[1]['event']=='book_progress'

def test_source_files_never_deleted_automatically(tmp_path):
    src=tmp_path/'source.mp3'; src.write_text('audio'); db=db_session(); b=Book(source_path=str(src),status=BookStatus.staging); db.add(b); db.flush(); db.add(BookMetadata(book_id=b.id,title='T',target_bitrate=64,target_channels=1)); db.commit(); ConversionJobService(db).launch([b.id], dry_run=True); assert src.exists()
