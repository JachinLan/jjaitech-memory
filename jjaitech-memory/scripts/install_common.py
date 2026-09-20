"""Transactional local deployment helpers. Never remove Wiki data on rollback."""
import copy
import contextlib
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import re
import subprocess

PLUGIN='jjaitech-memory@jjaitech-local'
MARKET='jjaitech-local'
MEMORY_TOOLS=['mcp__jjaitech-memory__'+name for name in ('write_memory','defer_memory','search_memory')]


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.jjaitech-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def with_vault_permission(settings, vault):
    result=copy.deepcopy(settings)
    if not isinstance(result,dict):raise ValueError('settings must be an object')
    sandbox=result.setdefault('sandbox',{})
    if not isinstance(sandbox,dict):raise ValueError('sandbox must be an object')
    filesystem=sandbox.setdefault('filesystem',{})
    if not isinstance(filesystem,dict):raise ValueError('filesystem must be an object')
    allow=filesystem.setdefault('allowWrite',[])
    if not isinstance(allow,list) or any(not isinstance(x,str) for x in allow):
        raise ValueError('filesystem.allowWrite must be a string array')
    normalized=lambda x:os.path.normcase(os.path.normpath(str(Path(x).expanduser())))
    added=not any(normalized(x)==normalized(vault) for x in allow)
    if added:allow.append(Path(vault).as_posix())
    return result,added


def with_memory_tool_permissions(settings):
    result=copy.deepcopy(settings)
    permissions=result.setdefault('permissions',{})
    if not isinstance(permissions,dict):raise ValueError('permissions must be an object')
    allow=permissions.setdefault('allow',[])
    if not isinstance(allow,list) or any(not isinstance(x,str) for x in allow):raise ValueError('permissions.allow must be a string array')
    added=[name for name in MEMORY_TOOLS if name not in allow]
    allow.extend(added)
    return result,added


def restore_owned_config(config, before, vault, permission_added, tool_rules_added=()):
    # Restore only plugin-owned keys; never replace all settings with a stale copy.
    path=config/'settings.json';current=read(path,{})
    plugins=current.setdefault('enabledPlugins',{})
    old=before.get('settings.json',{}).get('enabledPlugins',{})
    if PLUGIN in old:plugins[PLUGIN]=old[PLUGIN]
    else:plugins.pop(PLUGIN,None)
    if not plugins and 'enabledPlugins' not in before.get('settings.json',{}):current.pop('enabledPlugins',None)
    if permission_added:
        fs=current.get('sandbox',{}).get('filesystem',{})
        fs['allowWrite']=[x for x in fs.get('allowWrite',[]) if os.path.normcase(os.path.normpath(x))!=os.path.normcase(os.path.normpath(str(vault)))]
        original_fs=before.get('settings.json',{}).get('sandbox',{}).get('filesystem',{})
        if not fs.get('allowWrite') and 'allowWrite' not in original_fs:fs.pop('allowWrite',None)
        if not fs and 'filesystem' not in before.get('settings.json',{}).get('sandbox',{}):current.get('sandbox',{}).pop('filesystem',None)
        if not current.get('sandbox') and 'sandbox' not in before.get('settings.json',{}):current.pop('sandbox',None)
    if tool_rules_added:
        permissions=current.get('permissions',{})
        permissions['allow']=[x for x in permissions.get('allow',[]) if x not in tool_rules_added]
        old_permissions=before.get('settings.json',{}).get('permissions',{})
        if not permissions.get('allow') and 'allow' not in old_permissions:permissions.pop('allow',None)
        if not permissions and 'permissions' not in before.get('settings.json',{}):current.pop('permissions',None)
    write(path,current)
    for relative,key,parent in [('plugins/installed_plugins.json',PLUGIN,'plugins'),('plugins/known_marketplaces.json',MARKET,None)]:
        target=config/relative
        if not target.exists():continue
        latest=read(target,{})
        old=before.get(relative) or {}
        latest_map=latest.setdefault(parent,{}) if parent else latest
        old_map=old.get(parent,{}) if parent else old
        if key in old_map:latest_map[key]=old_map[key]
        else:latest_map.pop(key,None)
        write(target,latest)


@contextlib.contextmanager
def installation_lock(config):
    config=Path(config)
    if config.is_symlink() or (config/'jjaitech-memory-install.lock').is_symlink():raise ValueError('installation lock/config symlink forbidden')
    config.mkdir(parents=True,exist_ok=True)
    with (config/'jjaitech-memory-install.lock').open('a+b') as f:
        f.seek(0,2)
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise RuntimeError('Another jjaitech-memory installer is active; wait for it to finish.')
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f,fcntl.LOCK_UN)


def verify_registration(config,version):
    settings=read(Path(config)/'settings.json',{})
    if settings.get('enabledPlugins',{}).get(PLUGIN) is not True:raise RuntimeError('Plugin not enabled after CLI registration')
    rows=read(Path(config)/'plugins/installed_plugins.json',{}).get('plugins',{}).get(PLUGIN,[])
    if not rows or not any(r.get('version')==version and Path(r.get('installPath','')).is_dir() for r in rows):raise RuntimeError('Installed registry/version/path did not verify')
    return 'registered-and-enabled'


def verify_local_runtime(target,config):
    """No account/model requests. Exercise installed launcher, stdio MCP and Raw."""
    target=Path(target);spec=read(target/'.mcp.json')['mcpServers']['jjaitech-memory']
    args=[spec['command'],*[x.replace('${CODEBUDDY_PLUGIN_ROOT}',str(target)) for x in spec['args']]]
    with tempfile.TemporaryDirectory(prefix='jjaitech-install-check-') as folder:
        root=Path(folder);env=dict(os.environ,JJAITECH_WIKI_ROOT=str(root/'wiki'),CODEBUDDY_CONFIG_DIR=str(config))
        messages='\n'.join(json.dumps({'jsonrpc':'2.0','id':i,'method':method}) for i,method in enumerate(['initialize','tools/list'],1))+'\n'
        result=subprocess.run(args,input=messages,text=True,encoding='utf-8',env=env,capture_output=True,check=True,timeout=30)
        replies=[json.loads(x) for x in result.stdout.splitlines()]
        if {t['name'] for t in replies[-1]['result']['tools']}!={'write_memory','defer_memory','search_memory'}:raise RuntimeError('Local MCP check failed')
        transcript=root/'session.jsonl';transcript.write_text(json.dumps({'role':'user','content':'Synthetic installation check.'})+'\n',encoding='utf-8')
        hook=[args[0],args[1],'hook','SessionEnd']
        payload=json.dumps({'session_id':'installer-synthetic','transcript_path':str(transcript)})
        for _ in range(2):subprocess.run(hook,input=payload,text=True,encoding='utf-8',env=env,capture_output=True,check=True,timeout=30)
        files=list((root/'wiki/Raw').glob('*.jsonl'))
        if len(files)!=1 or files[0].read_bytes()!=transcript.read_bytes():raise RuntimeError('Raw hook/dedup check failed')
    return 'local-mcp-and-raw-passed; desktop-model-not-tested'


def deploy(source, config, vault, python, run_cli, bash=None, verify=False):
    with installation_lock(config):return _deploy(source,config,vault,python,run_cli,bash,verify)


def _deploy(source, config, vault, python, run_cli, bash=None, verify=False):
    """run_cli(argv) must raise on failure. Validate before granting any permission."""
    source,config,vault=Path(source).absolute(),Path(config).absolute(),Path(vault).absolute()
    if any(p.is_symlink() for p in [source,config,vault]):raise ValueError('installation symlinks require manual review')
    os.umask(0o077)
    for p in source.rglob('*'):
        if p.is_symlink():raise ValueError('plugin package symlinks forbidden')
    before={name:read(config/name,{}) for name in ['settings.json','plugins/installed_plugins.json','plugins/known_marketplaces.json']}
    candidate_settings,permission_added=with_vault_permission(before['settings.json'],vault)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=config/'jjaitech-memory-backups'/stamp
    market=config/'local-marketplaces'/MARKET
    target=market/'jjaitech-memory'
    backup.mkdir(parents=True)
    for name,value in before.items():write(backup/name,value)
    # Staging under the same filesystem allows an atomic directory rename.
    market.mkdir(parents=True,exist_ok=True)
    staged=market/('.stage-'+uuid.uuid4().hex)
    shutil.copytree(source,staged,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    import shlex
    hooks=read(staged/'hooks/hooks.json')
    for event,groups in hooks['hooks'].items():
        for group in groups:
            for hook in group['hooks']:
                hook['command']=shlex.quote(Path(python).as_posix())+' -X utf8 "${CODEBUDDY_PLUGIN_ROOT}/scripts/memory.py" hook '+event
    write(staged/'hooks/hooks.json',hooks)
    mcp=read(staged/'.mcp.json',None)
    if mcp:
        mcp['mcpServers']['jjaitech-memory']['command']=str(Path(python))
        write(staged/'.mcp.json',mcp)
    if (staged/'scripts/run-memory.sh').exists():
        shell=str(bash) if bash else '/bin/bash'
        if any('\n' in str(v) or '\r' in str(v) for v in (python,config,shell)):raise ValueError('runtime paths cannot contain line breaks')
        (staged/'.runtime-python-paths').write_text(Path(python).as_posix()+'\n',encoding='utf-8')
        (staged/'.runtime-config-root').write_text(config.as_posix()+'\n',encoding='utf-8')
        for event,groups in hooks['hooks'].items():
            for group in groups:
                for hook in group['hooks']:
                    hook['command']=shlex.quote(Path(shell).as_posix())+' "${CODEBUDDY_PLUGIN_ROOT}/scripts/run-memory.sh" hook '+event
        write(staged/'hooks/hooks.json',hooks)
        if mcp:
            mcp['mcpServers']['jjaitech-memory']['command']=shell
            mcp['mcpServers']['jjaitech-memory']['args']=['${CODEBUDDY_PLUGIN_ROOT}/scripts/run-memory.sh','mcp']
            write(staged/'.mcp.json',mcp)
    old_manifest=read(market/'.codebuddy-plugin/marketplace.json',None)
    old_target=backup/'previous-plugin'
    receipt={'status':'staged','version':read(staged/'.codebuddy-plugin/plugin.json')['version'],
             'vault':str(vault),'permission_added':permission_added,'backup':str(backup)}
    write(backup/'receipt.json',receipt)
    tool_rules_added=[]
    env_changes={}
    installed=False
    old_moved=False
    try:
        run_cli(['plugin','validate',str(staged)])
        # Preserve the existing database BEFORE any new code can migrate it.
        dbfile=vault/'.state/memory.sqlite3'
        if dbfile.exists():
            with contextlib.closing(sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)) as db, contextlib.closing(sqlite3.connect(backup/'pre-upgrade.sqlite3')) as saved:
                db.backup(saved)
        if target.exists():
            target.rename(old_target)
            old_moved=True
        staged.rename(target);installed=True
        write(market/'.codebuddy-plugin/marketplace.json',{'name':MARKET,'owner':{'name':'JJ AI TECH'},'plugins':[{'name':'jjaitech-memory','source':'./jjaitech-memory'}]})
        # Re-read settings after validation to preserve unrelated concurrent changes.
        fresh,permission_added=with_vault_permission(read(config/'settings.json',{}),vault)
        if mcp:fresh,tool_rules_added=with_memory_tool_permissions(fresh)
        if bash:
            runtime_env=fresh.setdefault('env',{})
            if not isinstance(runtime_env,dict):raise ValueError('settings.env must be an object')
            key='CODEBUDDY_CODE_GIT_BASH_PATH'
            desired=str(bash)
            if runtime_env.get(key)!=desired:
                env_changes[key]={'existed':key in runtime_env,'before':runtime_env.get(key),'installed':desired}
                runtime_env[key]=desired
        write(config/'settings.json',fresh)
        for args in [['plugin','marketplace','add',str(market)],['plugin','install',PLUGIN],['plugin','update',PLUGIN]]:
            run_cli(args)
        if verify:
            receipt['verification']=verify_registration(config,receipt['version'])
            rows=read(config/'plugins/installed_plugins.json',{}).get('plugins',{}).get(PLUGIN,[])
            installed_path=next(Path(r['installPath']) for r in rows if r.get('version')==receipt['version'])
            receipt['runtime_check']=verify_local_runtime(installed_path,config)
        receipt.update(status='installed',permission_added=permission_added,added_tool_rules=tool_rules_added,env_changes=env_changes)
        write(backup/'receipt.json',receipt)
        return receipt
    except Exception as exc:
        rollback_errors=[]
        if installed or old_moved:
            if installed:
                try:
                    restore_owned_config(config,before,vault,permission_added,tool_rules_added)
                    current=read(config/'settings.json',{});environment=current.get('env',{})
                    for key,change in env_changes.items():
                        if environment.get(key)==change['installed']:
                            if change['existed']:environment[key]=change['before']
                            else:environment.pop(key,None)
                    if not environment and 'env' not in before['settings.json']:current.pop('env',None)
                    write(config/'settings.json',current)
                except Exception as error:rollback_errors.append('settings:'+type(error).__name__)
            # Keep the failed candidate as evidence rather than deleting it.
            try:
                if target.exists():target.rename(backup/'failed-plugin')
                if old_target.exists():old_target.rename(target)
                manifest=market/'.codebuddy-plugin/marketplace.json'
                if old_manifest is not None:write(manifest,old_manifest)
                elif manifest.exists():manifest.rename(backup/'failed-marketplace.json')
            except Exception as error:rollback_errors.append('plugin-files:'+type(error).__name__)
        receipt.update(status=('rollback-incomplete' if rollback_errors else 'failed-rolled-back') if installed or old_moved else 'validation-failed-no-permission-change',
                       error=type(exc).__name__,rollback_errors=rollback_errors)
        write(backup/'receipt.json',receipt)
        raise


def revoke_owned_permission(config, receipt):
    """Explicit admin action; remove only grants this installation introduced."""
    if not receipt.get('permission_added') and not receipt.get('added_tool_rules'):return False
    path=Path(config)/'settings.json';settings=read(path,{})
    previous=copy.deepcopy(settings)
    if receipt.get('permission_added'):
        fs=settings.get('sandbox',{}).get('filesystem',{})
        fs['allowWrite']=[x for x in fs.get('allowWrite',[]) if os.path.normcase(os.path.normpath(x))!=os.path.normcase(os.path.normpath(receipt['vault']))]
    if receipt.get('added_tool_rules'):
        permissions=settings.get('permissions',{})
        permissions['allow']=[x for x in permissions.get('allow',[]) if x not in receipt['added_tool_rules']]
    write(path,settings)
    return previous!=settings
