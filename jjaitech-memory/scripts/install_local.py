#!/usr/bin/env python3
"""Mac preflight + transactional plugin registration. Vault migration runs in hooks."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shlex
import shutil
import sqlite3
import subprocess
import sys
from install_common import deploy


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',type=Path)
    parser.add_argument('--config-dir',type=Path,default=Path(os.environ.get('WORKBUDDY_CONFIG_DIR',str(Path.home()/'.workbuddy'))))
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if platform.system()!='Darwin':raise RuntimeError('Use the Windows installer on Windows.')
    if sys.version_info<(3,9):raise RuntimeError('Python 3.9+ required')
    import fcntl
    with sqlite3.connect(':memory:') as db:db.execute('CREATE VIRTUAL TABLE check_fts USING fts5(text)')
    candidates=[args.app] if args.app else [Path('/Applications/WorkBuddy.app'),Path.home()/'Applications/WorkBuddy.app']
    apps=[p for p in candidates if p and (p/'Contents/Resources/app.asar.unpacked/cli/bin/codebuddy').is_file()]
    if len(apps)!=1:raise RuntimeError('Cannot uniquely locate WorkBuddy. Pass --app with its actual .app path.')
    app=apps[0];cli=app/'Contents/Resources/app.asar.unpacked/cli/bin/codebuddy'
    config=args.config_dir.expanduser().absolute()
    if not config.is_dir():raise RuntimeError('Open WorkBuddy and log in first.')
    nodes=[Path(shutil.which('node'))] if shutil.which('node') else []
    nodes+=list((config/'binaries/node/versions').glob('*/bin/node'))
    node=None
    for candidate in nodes:
        try:
            version=subprocess.check_output([str(candidate),'--version'],text=True,timeout=10).strip()
            if tuple(map(int,version.lstrip('v').split('.')[:3]))>=(18,20,8):node=candidate;break
        except (ValueError,OSError,subprocess.SubprocessError):pass
    if node is None:raise RuntimeError('Node.js 18.20.8+ not found')
    env=dict(os.environ,CODEBUDDY_CONFIG_DIR=str(config),DISABLE_TELEMETRY='1',DISABLE_GALILEO='1')
    def run_cli(arguments):
        return subprocess.run([str(node),str(cli),*arguments],env=env,check=True,timeout=180)
    print('WorkBuddy',plistlib.loads((app/'Contents/Info.plist').read_bytes()).get('CFBundleShortVersionString'))
    run_cli(['--version'])
    source=Path(__file__).resolve().parents[1]
    if args.check:
        run_cli(['plugin','validate',str(source)]);return
    processes=subprocess.check_output(['ps','-u',str(os.getuid()),'-o','command='],text=True)
    executable=str(app/'Contents/MacOS/Electron')
    if any(line.strip().startswith(executable) or
           (Path(line.strip().split(' ')[0]).name in ('node','codebuddy','cbc') and str(cli.parent.parent) in line)
           for line in processes.splitlines() if line.strip()):
        raise RuntimeError('Finish pending work and quit WorkBuddy / its CodeBuddy sessions before upgrading; do not mix old and new Hooks on one vault.')
    result=deploy(source,config,Path.home()/'AI-Wiki',sys.executable,run_cli)
    bin_dir=Path.home()/'.local/bin';bin_dir.mkdir(parents=True,exist_ok=True)
    wrapper=bin_dir/'jjaitech-codebuddy'
    wrapper.write_text('#!/bin/sh\nexport CODEBUDDY_CONFIG_DIR='+shlex.quote(str(config))+'\nexport DISABLE_TELEMETRY=1\nexport DISABLE_GALILEO=1\nexec '+shlex.quote(str(node))+' '+shlex.quote(str(cli))+' "$@"\n',encoding='utf-8')
    wrapper.chmod(0o700)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('Registration completed. Restart WorkBuddy; hooks initialize the vault. Run doctor and the acceptance checks before rollout.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('INSTALL STOPPED: '+str(error),file=sys.stderr);sys.exit(1)
