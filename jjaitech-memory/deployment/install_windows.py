"""Windows pilot installer. No credentials/data are included or copied from another user."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile


def discover_cli(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    roots = []
    # Inspect actual running WorkBuddy executable locations, then registry installs.
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-Command',
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); Get-Process WorkBuddy -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path -Unique"],
            capture_output=True, text=True, encoding='utf-8', timeout=15)
        roots += [Path(x.strip()).parent for x in result.stdout.splitlines() if x.strip().lower().endswith('.exe')]
    except (OSError, subprocess.TimeoutExpired):
        pass
    import winreg
    for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
        for key in [r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                    r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall']:
            try:
                with winreg.OpenKey(hive,key) as base:
                    for i in range(winreg.QueryInfoKey(base)[0]):
                        try:
                            with winreg.OpenKey(base,winreg.EnumKey(base,i)) as item:
                                name=winreg.QueryValueEx(item,'DisplayName')[0]
                                if 'workbuddy' in name.lower():
                                    roots.append(Path(winreg.QueryValueEx(item,'InstallLocation')[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    for key in ['LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)']:
        base=os.environ.get(key)
        if base:
            roots += [Path(base)/'WorkBuddy',Path(base)/'Programs/WorkBuddy']
    for root in roots:
        candidates += [root/'resources/app.asar.unpacked/cli/bin/codebuddy',root/'resources/cli/bin/codebuddy']
    found = list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))
    if explicit and Path(explicit).is_file():
        return Path(explicit).resolve()
    if len(found) != 1:
        raise RuntimeError('Cannot uniquely locate WorkBuddy bundled CLI. Pass --cli with its actual path. Found: '+str(found))
    return found[0]


def find_node(config):
    nodes = []
    nodes += list((config/'binaries/node/versions').glob('*/node.exe'))
    nodes += list((config/'binaries/node/versions').glob('*/bin/node.exe'))
    if shutil.which('node'):nodes.append(Path(shutil.which('node')))
    for node in nodes:
        try:
            out=subprocess.check_output([str(node),'--version'],text=True,timeout=10).strip()
            nums=tuple(int(x) for x in out.lstrip('v').split('.')[:3])
            if nums >= (18,20,8):
                return node,out
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    raise RuntimeError('Node.js 18.20.8+ not found. Install official Node.js or supply its directory in PATH.')


def find_bash(config=None):
    candidates = [os.environ.get('CODEBUDDY_CODE_GIT_BASH_PATH')]
    if config and (config/'settings.json').exists():
        settings=json.loads((config/'settings.json').read_text(encoding='utf-8-sig'))
        candidates.append(settings.get('env',{}).get('CODEBUDDY_CODE_GIT_BASH_PATH'))
    for key in ['ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA']:
        base=os.environ.get(key)
        if base:
            candidates += [str(Path(base)/'Git/bin/bash.exe'),str(Path(base)/'Programs/Git/bin/bash.exe')]
    git=shutil.which('git')
    if git:
        candidates += [str(Path(git).parent.parent/'bin/bash.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                subprocess.run([candidate,'--version'],check=True,capture_output=True,timeout=10)
                return Path(candidate)
            except (OSError,subprocess.SubprocessError):continue
    raise RuntimeError('Git for Windows / Git Bash not found. Install it from git-scm.com first.')


def atomic_json(path, value):
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.jjaitech-')
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
    os.replace(temp,path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cli',help='Actual path to the bundled cli/bin/codebuddy JS entrypoint')
    parser.add_argument('--config-dir',default=str(Path.home()/'.workbuddy'))
    parser.add_argument('--check',action='store_true',help='Read-only checks; no installation')
    parser.add_argument('--consent',action='store_true',help='Explicit agreement to the permissions described below')
    args=parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Windows pilot installer only; use the separate Mac package on macOS.')
    if sys.version_info < (3,9):
        raise RuntimeError('Python 3.9+ required.')
    import msvcrt
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE VIRTUAL TABLE preflight USING fts5(text)')
    config=Path(args.config_dir).expanduser().resolve()
    if not config.is_dir():
        raise RuntimeError('WorkBuddy config not found; open WorkBuddy and log in to your own account first.')
    cli=discover_cli(args.cli)
    node,node_version=find_node(config)
    bash=find_bash(config)
    env=dict(os.environ,CODEBUDDY_CONFIG_DIR=str(config),DISABLE_TELEMETRY='1',DISABLE_GALILEO='1',
             CODEBUDDY_CODE_GIT_BASH_PATH=str(bash),
             PATH=str(node.parent)+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH',''))
    version=subprocess.check_output([str(node),str(cli),'--version'],env=env,text=True,timeout=30).strip()
    print(json.dumps({'python':sys.executable,'node':str(node),'node_version':node_version,
                      'cli':str(cli),'cli_version':version,'config':str(config),'git_bash':str(bash)},ensure_ascii=False,indent=2))
    if args.check:
        return
    active=subprocess.run(['powershell.exe','-NoProfile','-Command',
        "Get-Process WorkBuddy -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
        capture_output=True,text=True,timeout=15)
    cli_literal="'"+str(cli).replace("'","''")+"'"
    sessions=subprocess.run(['powershell.exe','-NoProfile','-Command',
        "$ErrorActionPreference='Stop'; $jjCli="+cli_literal+"; Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe','codebuddy.exe','cbc.exe') -and $_.CommandLine -and $_.CommandLine.Contains($jjCli) } | Select-Object -ExpandProperty ProcessId"],capture_output=True,text=True,timeout=20,check=True)
    if active.stdout.strip() or sessions.stdout.strip():
        raise RuntimeError('Finish pending tasks and quit WorkBuddy before installation. Re-run with --cli if needed; do not mix old and new Hooks on one vault.')
    print('This is a Windows pilot build, not yet tested on a physical Windows computer.')
    print('Installs only local plugin code. Creates YOUR ~/AI-Wiki, permits ALL WorkBuddy tools to write that vault,')
    print('Adds only the three local jjaitech-memory MCP tool permissions (write, defer, search).')
    print('and lets your current WorkBuddy model process new conversations and selected Wiki text. No extra model API or cloud sync.')
    if not args.consent and input('Type YES to install, or anything else to cancel: ').strip()!='YES':
        print('Cancelled.');return
    candidate=Path(__file__).resolve().parent/'jjaitech-memory'
    source=candidate if candidate.exists() else Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(source/'scripts'))
    from install_common import deploy
    def run_cli(arguments):
        subprocess.run([str(node),str(cli),*arguments],env=env,check=True,timeout=180)
    result=deploy(source,config,Path.home()/'AI-Wiki',sys.executable,run_cli,bash=bash,verify=True)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('Registration verified; local Python/runtime checks passed. Restart WorkBuddy; hooks initialize the vault. Complete Windows acceptance before wider rollout.')


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('INSTALL STOPPED: '+str(error),file=sys.stderr)
        sys.exit(1)
