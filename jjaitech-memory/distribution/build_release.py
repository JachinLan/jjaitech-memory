"""Build an allowlisted, data-free Windows release and an HTTPS/hash-pinned command."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['.codebuddy-plugin/plugin.json','.mcp.json','hooks/hooks.json','scripts/memory.py','scripts/sources.py','scripts/quality.py','scripts/memory_mcp.py','scripts/retrieval_guard.py',
       'scripts/portable.py','scripts/install_common.py','scripts/install_local.py','scripts/run-memory.sh','deployment/install_windows.py',
       'distribution/bootstrap-windows.ps1','distribution/bootstrap-macos.sh']


def check_url(url):
    p=urlsplit(url)
    if (p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment
        or not re.fullmatch(r'[A-Za-z0-9.:-]+',p.netloc)
        or not re.fullmatch(r'/[A-Za-z0-9/_%.-]*',p.path)):
        raise ValueError('Use an HTTPS public asset URL without credentials, query, fragment or shell characters')
    if re.search(r'%0[ad]',p.path,re.I):raise ValueError('URL cannot contain line breaks')
    return url


def command(url, sha):
    check_url(url)
    if not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('invalid SHA256')
    # Intended to be pasted as ONE command in Windows PowerShell. It never changes
    # execution policy; corporate signing restrictions are checked before download.
    parts=["$ErrorActionPreference='Stop'",
      "if (@(Get-ExecutionPolicy -List | Where-Object {$_.ExecutionPolicy -in @('AllSigned','Restricted')}).Count) {throw 'IT signing policy restricts this installer'}",
      "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12",
      "$jjDir=Join-Path $env:TEMP ('jjaitech-install-'+[guid]::NewGuid().ToString('N'))",
      "New-Item -ItemType Directory -Path $jjDir | Out-Null",
      "$jjZip=Join-Path $jjDir 'release.zip'",
      f"for ($jjAttempt=1; $jjAttempt -le 3; $jjAttempt++) {{try {{Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile $jjZip -TimeoutSec 120; break}} catch {{if ($jjAttempt -eq 3) {{throw}}; Start-Sleep -Seconds 2}}}}",
      f"if ((Get-FileHash -Algorithm SHA256 -LiteralPath $jjZip).Hash.ToLowerInvariant() -ne '{sha}') {{throw 'Download checksum mismatch; installation stopped'}}",
      "Expand-Archive -LiteralPath $jjZip -DestinationPath $jjDir",
      "& ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $jjDir 'jjaitech-memory/distribution/bootstrap-windows.ps1')))) -PackageRoot $jjDir"]
    return '; '.join(parts)


def mac_command(url,sha):
    import shlex
    check_url(url)
    if not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('invalid SHA256')
    return """#!/bin/bash
set -eu
if [ "$(uname -s)" != Darwin ]; then echo 'This command requires macOS.' >&2; exit 1; fi
jj_dir=$(mktemp -d "${TMPDIR:-/tmp}/jjaitech-install.XXXXXX")
trap 'rm -rf -- "$jj_dir"' EXIT
curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 --output "$jj_dir/release.zip" """+shlex.quote(url)+"""
jj_hash=$(shasum -a 256 "$jj_dir/release.zip" | awk '{print $1}')
if [ "$jj_hash" != """+shlex.quote(sha)+""" ]; then echo 'Download checksum mismatch; stopped.' >&2; exit 1; fi
unzip -q "$jj_dir/release.zip" -d "$jj_dir/package"
bash "$jj_dir/package/jjaitech-memory/distribution/bootstrap-macos.sh" "$jj_dir/package" "$@"
"""


def build(output,base_url=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    version=json.loads((ROOT/FILES[0]).read_text())['version']
    name=f'jjaitech-memory-{version}-online.1.zip'
    archive=output/name
    if archive.exists():raise ValueError('Release already exists; use a new output directory or explicit new release revision')
    hashes={rel:hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() for rel in FILES}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for rel in FILES:
            f=ROOT/rel
            if f.is_symlink():raise ValueError('symlinks forbidden in release')
            z.write(f,'jjaitech-memory/'+rel)
        z.writestr('SOURCE_SHA256.json',json.dumps(hashes,indent=2)+'\n')
    with zipfile.ZipFile(archive) as z:
        if z.testzip():raise ValueError('ZIP integrity failure')
        assert set(z.namelist())=={'jjaitech-memory/'+x for x in FILES}|{'SOURCE_SHA256.json'}
        for rel,expected in hashes.items():
            assert hashlib.sha256(z.read('jjaitech-memory/'+rel)).hexdigest()==expected
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest={'plugin_version':version,'distribution_revision':1,'asset':name,'sha256':checksum,
              'windows_native_test':'NOT RUN','status':'pilot-unpublished','wiki_data_included':False,
              'source_files':hashes}
    if base_url:
        url=check_url(base_url.rstrip('/')+'/'+name)
        manifest['planned_url']=url
        (output/'INSTALL-COMMAND.txt').write_text(command(url,checksum)+'\n')
        (output/'install-macos.sh').write_text(mac_command(url,checksum))
    (output/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (output/'SHA256SUMS.txt').write_text(checksum+'  '+name+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--base-url')
    a=p.parse_args();print(json.dumps(build(a.output,a.base_url),indent=2))
