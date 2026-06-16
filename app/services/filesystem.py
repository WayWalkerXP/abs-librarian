from __future__ import annotations
import shutil
from pathlib import Path
class FilesystemService:
    def move(self, source:Path, dest:Path):
        dest.parent.mkdir(parents=True, exist_ok=True); return shutil.move(str(source), str(dest))
    def archive_success(self, source:Path, converted_dir:Path): return self.move(source, converted_dir/source.name)
    def archive_failed(self, source:Path, failed_dir:Path): return self.move(source, failed_dir/source.name)
    def list_archive(self, converted_dir:Path)->list[str]: return [str(p) for p in converted_dir.rglob('*') if p.is_file()]
