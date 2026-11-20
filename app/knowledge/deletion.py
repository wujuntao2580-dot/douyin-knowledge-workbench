"""Delete only registered, selected single files; preserve shared folders and source catalogs."""
import ctypes
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


def recycle(path):
    if os.name != 'nt':
        raise OSError('文件删除仅支持 Windows 回收站')
    from ctypes import wintypes

    class Operation(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT), ('pFrom', wintypes.LPCWSTR),
                    ('pTo', wintypes.LPCWSTR), ('fFlags', wintypes.WORD), ('aborted', wintypes.BOOL),
                    ('mappings', ctypes.c_void_p), ('progressTitle', wintypes.LPCWSTR)]

    request = Operation(None, 3, str(path) + '\0\0', None, 0x40 | 0x10 | 0x04 | 0x400, False, None, None)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(request))
    if result or request.aborted:
        raise OSError(f'无法移入系统回收站（{result}）')


def candidate_files(project, page, catalog, ids, kinds=None):
    project, page = Path(project).resolve(), Path(page).resolve()
    portable = (project / 'app/catalog').is_dir()
    workflow = project / ('data/workflow' if portable else 'work/creator-workflow')
    registry_file = project / ('data/creators.json' if portable else 'work/xingzhe-summary-demo/creators.json')
    compressed = project / ('data/compressed' if portable else 'work/video-compression/media')
    registry = json.loads(registry_file.read_text('utf-8')) if registry_file.is_file() else {}
    queue = json.loads((workflow / 'queue.json').read_text('utf-8')) if (workflow / 'queue.json').is_file() else {'batches': []}
    result = {key: set() for key in ('media', 'transcript', 'summary')}
    kinds = set(result) if kinds is None else kinds
    protected = set()

    def path_from_link(link):
        if not link:
            return None
        parsed = urlsplit(link)
        if parsed.scheme == 'file':
            return Path(url2pathname(parsed.path)).absolute()
        if parsed.scheme or parsed.netloc:
            return None
        return (page.parent / unquote(link)).absolute()

    def add(kind, path, inside=False):
        if kind not in kinds:
            return
        path = Path(os.path.abspath(path))
        if path.suffix.lower() not in {'media': {'.mp4'}, 'transcript': {'.md', '.srt', '.json'}, 'summary': {'.json'}}[kind]:
            return
        if inside and not path.is_relative_to(project):
            raise ValueError('登记的资料路径超出项目，未执行删除')
        # Never traverse junctions/symlinks for a destructive operation.
        for parent in [path, *path.parents]:
            if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
                raise ValueError('删除目标经过目录链接，请先核对真实文件位置')
        if path.is_file():
            result[kind].add(path)

    for video in catalog['videos']:
        path = path_from_link(video.get('local', ''))
        if video['id'] not in ids:
            if path:
                protected.add(path.resolve())
            continue
        if path:
            add('media', path)
        subtitle = path_from_link(video.get('subtitle', ''))
        if subtitle:
            add('transcript', subtitle, True)
            add('transcript', subtitle.with_suffix('.md'), True)
        add('media', compressed / (video['id'] + '.mp4'), True)

    for creator in registry.values():
        for ident in ids:
            for key, suffixes in [('records', ['.json']), ('subtitles', ['.md', '.srt']), ('summaries', ['.json'])]:
                if creator.get(key):
                    for suffix in suffixes:
                        add('summary' if key == 'summaries' else 'transcript', project / creator[key] / (ident + suffix), True)
            if creator.get('records'):
                visual = (project / creator['records']).parent / 'visual-text'
                add('transcript', visual / (ident + '.json'), True)
                add('summary', visual / (ident + '.summary.json'), True)
            if creator.get('media'):
                media = project / creator['media']
                if not media.absolute().is_relative_to(project):
                    raise ValueError('登记的媒体目录超出项目')
                for path in media.glob(ident + '*.mp4'):
                    if re.match(re.escape(ident) + r'(?!\d)', path.stem):
                        add('media', path, True)
            for filename in creator.get('catalogs', []):
                snapshot = (project / filename).resolve()
                if not snapshot.is_relative_to(project):
                    raise ValueError('登记的清单路径超出项目')
                if snapshot.is_file():
                    for work in json.loads(snapshot.read_text('utf-8-sig')).get('works', []):
                        key = str(work.get('videoId', ''))
                        if work.get('workbenchMedia'):
                            path = Path(work['workbenchMedia'])
                            if key in ids:
                                add('media', path)
                            else:
                                protected.add(path.resolve())

    for batch in queue['batches']:
        for row in batch['works']:
            if row['id'] not in ids:
                if row.get('file'):
                    protected.add(Path(row['file']).resolve())
                continue
            if row.get('file'):
                add('media', row['file'])
            directory = workflow / 'batches' / batch['id']
            add('transcript', directory / 'records' / (row['id'] + '.json'), True)
            for suffix in ('.md', '.srt'):
                add('transcript', directory / 'transcripts' / (row['id'] + suffix), True)
    if not portable:
        for ident in ids:
            add('transcript', project / 'work/xingzhe-library' / (ident + '.json'), True)
    for paths in result.values():
        if any(path.resolve() in protected for path in paths):
            raise ValueError('某个文件还被其他视频引用，未执行删除；请先核对文件关联')
    return result


def delete_selected(store, payload, catalog, recycle_file=recycle):
    ids = payload.get('ids', [])
    available = {video['id'] for video in catalog['videos']}
    if not isinstance(ids, list) or not ids or len(ids) > 3000 or any(not isinstance(ident, str) or not re.fullmatch(r'\d{19}', ident) or ident not in available for ident in ids):
        raise ValueError('请选择有效的视频后再删除')
    ids = set(ids)
    choices = payload.get('choices', {})
    if not isinstance(choices, dict) or not any(choices.get(key) is True for key in ('record', 'media', 'transcript', 'summary')):
        raise ValueError('请至少勾选一项删除内容')
    files = candidate_files(store.path.parents[1], store.page, catalog, ids, {key for key in ('media', 'transcript', 'summary') if choices.get(key) is True})
    failures, removed = [], 0
    success = {}
    with store.transaction() as state:
        if payload.get('revision') is not None and payload['revision'] != state['revision']:
            raise ValueError('内容已更新，请刷新后再删除')
        for kind, paths in files.items():
            success[kind] = choices.get(kind) is True
            if not success[kind]:
                continue
            for path in sorted(paths):
                try:
                    recycle_file(path)
                    removed += 1
                except OSError as error:
                    success[kind] = False
                    failures.append(f'{path.name}：{error}')
        for ident in ids:
            flags = state.setdefault('deletions', {}).setdefault(ident, {})
            for kind, complete in success.items():
                if complete:
                    flags[kind] = True
            if choices.get('record') is True and not failures:
                flags['record'] = True
                state['assignments'].pop(ident, None)
                for folder in state['folders'].values():
                    folder['items'] = [item for item in folder['items'] if item != ['video', ident]]
            flags['at'] = datetime.now().isoformat(timespec='seconds')
        result = store.project(state, catalog)
    result['revision'] = state['revision']
    result['deletionResult'] = {'filesRemoved': removed, 'recordsRemoved': len(ids) if choices.get('record') and not failures else 0, 'failures': failures}
    return result
