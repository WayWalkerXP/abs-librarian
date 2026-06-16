from __future__ import annotations
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.entities import AppSetting
PATH_KEYS=['incoming_dir','staging_dir','converting_dir','ready_for_library_dir','library_dir','converted_dir','failed_dir','logs_dir','temp_dir','metadata_backup_dir']
class SettingsService:
    def __init__(self, db:Session): self.db=db
    def defaults(self)->dict:
        s=get_settings(); return {k:getattr(s,k) for k in PATH_KEYS}|{'output_template':s.output_template,'abs_base_url':s.abs_base_url,'abs_api_token':s.abs_api_token,'abs_library_id':s.abs_library_id,'abs_cache_refresh_hours':s.abs_cache_refresh_hours,'default_bitrate_kbps':s.default_bitrate_kbps,'default_channels':s.default_channels,'max_concurrent_jobs':s.max_concurrent_jobs,'log_retention_days':s.log_retention_days}
    def get_all(self)->dict:
        data=self.defaults()
        for row in self.db.query(AppSetting).all(): data[row.key]=row.value.get('value')
        return data
    def set(self,key:str,value):
        self.db.merge(AppSetting(key=key,value={'value':value})); self.db.commit()
