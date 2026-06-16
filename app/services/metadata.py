from __future__ import annotations
FIELDS=['title','subtitle','author','narrator','series','series_sequence','description','asin','cover','chapters','duration','target_bitrate','target_channels','dramatic_audio']
def resolve_metadata(embedded:dict|None=None, yaml_data:dict|None=None, abs_cached:dict|None=None, manual:dict|None=None)->dict:
    result={}
    for source in (embedded or {}, yaml_data or {}, abs_cached or {}, manual or {}):
        for k,v in source.items():
            if k in FIELDS and v not in (None,'',[]): result[k]=v
    return result
def validate_conversion_settings(bitrate:int|None, channels:int|None)->list[str]:
    issues=[]
    if bitrate is None or not 25 <= int(bitrate) <= 384: issues.append('target_bitrate must be between 25 and 384 kbps')
    if channels not in (1,2): issues.append('target_channels must be 1 or 2')
    return issues
