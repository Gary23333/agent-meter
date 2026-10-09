"""Private local materialization for Node's ASAR-incompatible ESM loader.

Only code from the user's installed app is cached, never credentials. These
assets are not part of this project's distributable package or repository.
"""
import hashlib
import json
import os
import shutil
import struct
import tempfile
from pathlib import Path

from .model import SourceError

PACKAGES=("@qoder-ai/qoder-cn-agent-sdk","@modelcontextprotocol/sdk","zod","zod-to-json-schema",
          "ajv","ajv-formats","fast-uri","fast-deep-equal","json-schema-traverse","require-from-string","json-schema-typed")


def materialize_qoder_sdk(archive,runtime_dir):
    archive=Path(archive)
    stat=archive.stat()
    identity=hashlib.sha256((str(archive)+str(stat.st_size)+str(stat.st_mtime_ns)).encode()).hexdigest()[:20]
    cache=Path(runtime_dir)/"installed-sdk"/identity
    sdk=cache/"node_modules/@qoder-ai/qoder-cn-agent-sdk/dist/index.js"
    if (cache/".complete").is_file() and sdk.is_file():return sdk
    cache.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(dir=cache.parent) as temp:
        target=Path(temp)/"assets";target.mkdir(mode=0o700)
        copied=0
        with archive.open('rb') as handle:
            handle.seek(4);size=struct.unpack('<I',handle.read(4))[0]
            if not 8<=size<=32*1024*1024:raise SourceError('invalid_sdk_archive')
            handle.seek(16);tree=json.loads(handle.read(size-8).rstrip(b'\0'));base=8+size
            def write(node,relative):
                nonlocal copied
                if 'files' in node:
                    for name,child in node['files'].items():
                        if name in {'.','..'} or '/' in name or '\\' in name:raise SourceError('invalid_sdk_archive')
                        write(child,relative/name)
                elif 'size' in node:
                    copied+=node['size']
                    if copied>64*1024*1024:raise SourceError('sdk_cache_too_large')
                    output=target/relative;output.parent.mkdir(parents=True,exist_ok=True)
                    if node.get('unpacked'):
                        source=Path(str(archive)+'.unpacked')/relative
                        try:source.resolve().relative_to(Path(str(archive)+'.unpacked').resolve())
                        except ValueError:raise SourceError('sdk_asset_outside_bundle') from None
                        shutil.copyfile(source,output)
                    else:
                        handle.seek(base+int(node['offset']));output.write_bytes(handle.read(node['size']))
            for package in PACKAGES:
                relative=Path('node_modules')/package;entry=tree
                try:
                    for component in relative.parts:entry=entry['files'][component]
                except KeyError:
                    if package=='@qoder-ai/qoder-cn-agent-sdk':raise SourceError('qoder_sdk_not_installed')
                    continue
                # The worker already exists unpacked and is referenced explicitly.
                if package=='@qoder-ai/qoder-cn-agent-sdk':
                    entry={'files':{k:v for k,v in entry['files'].items() if k in {'package.json','LICENSE','dist'}}}
                    if 'dist' in entry['files']:
                        dist=entry['files']['dist']
                        entry['files']['dist']={'files':{k:v for k,v in dist['files'].items() if k!='_worker'}}
                write(entry,relative)
        (target/'.complete').write_text('installed-code-cache-only\n')
        try:os.rename(target,cache)
        # Rename onto an existing dir raises EEXIST/ENOTEMPTY: fine when the
        # winner finished; garbage when a crashed run left it incomplete.
        except OSError:
            if (cache/'.complete').is_file() and sdk.is_file():return sdk
            shutil.rmtree(cache,ignore_errors=True)
            try:os.rename(target,cache)
            except OSError:pass
    return sdk
