from __future__ import annotations
from pathlib import Path
import re
SAFE=re.compile(r'[^A-Za-z0-9 ._()\-]+')
def clean(v): return SAFE.sub('_', str(v or '').strip()).strip(' ._') or 'Unknown'
def render_output_path(template:str, metadata:dict)->Path:
    author=clean(metadata.get('author')); album=clean(metadata.get('album') or metadata.get('title'))
    series=clean(metadata.get('series')) if metadata.get('series') else ''
    seq=clean(metadata.get('series_sequence')) if metadata.get('series_sequence') else ''
    if not series and template == '{author}/{series}/{series_sequence} - {album}': return Path(author)/album
    rendered=template.format(author=author, album=album, title=album, series=series, series_sequence=seq).replace('//','/')
    parts=[clean(p) for p in rendered.split('/') if p and p.strip(' -')]
    return Path(*parts)
