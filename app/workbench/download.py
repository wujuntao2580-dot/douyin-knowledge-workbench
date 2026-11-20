"""Download a pinned artifact with resumable transfers and SHA-256 verification."""
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def download(url, path, expected):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and digest(path) == expected.casefold():
        print('Verified cached artifact:', path.name, flush=True)
        return
    partial = path.with_suffix(path.suffix + '.download')
    last_error = None
    for attempt in range(4):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {'User-Agent': 'DouyinKnowledgeWorkbench/1.1'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                resume = offset > 0 and response.status == 206
                if not resume:
                    offset = 0
                last = time.monotonic()
                with partial.open('ab' if resume else 'wb') as target:
                    while block := response.read(1024 * 1024):
                        target.write(block); offset += len(block)
                        if time.monotonic() - last >= 10:
                            print(f'{path.name}: {offset / 1024**2:.1f} MiB downloaded', flush=True)
                            last = time.monotonic()
            if digest(partial) != expected.casefold():
                partial.unlink()
                raise ValueError('SHA-256 mismatch; artifact was not installed')
            partial.replace(path)
            print('Verified download:', path.name, flush=True)
            return
        except urllib.error.HTTPError as error:
            if error.code == 416:
                if partial.exists() and digest(partial) == expected.casefold():
                    partial.replace(path)
                    return
                partial.unlink(missing_ok=True)
            last_error = error
        except (OSError, ValueError) as error:
            last_error = error
        if attempt < 3:
            time.sleep(2 + attempt)
    raise RuntimeError(f'Unable to download {path.name}: {last_error}')


if __name__ == '__main__':
    download(*sys.argv[1:4])
