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

PLUGIN='jjaitech-memory@jjaitech-local'
MARKET='jjaitech-local'


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


def restore_owned_config(config, before, vault, permission_added):
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


def deploy(source, config, vault, python, run_cli):
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
    old_manifest=read(market/'.codebuddy-plugin/marketplace.json',None)
    old_target=backup/'previous-plugin'
    receipt={'status':'staged','version':read(staged/'.codebuddy-plugin/plugin.json')['version'],
             'vault':str(vault),'permission_added':permission_added,'backup':str(backup)}
    write(backup/'receipt.json',receipt)
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
        write(config/'settings.json',fresh)
        for args in [['plugin','marketplace','add',str(market)],['plugin','install',PLUGIN],['plugin','update',PLUGIN]]:
            run_cli(args)
        receipt.update(status='installed',permission_added=permission_added)
        write(backup/'receipt.json',receipt)
        return receipt
    except Exception as exc:
        rollback_errors=[]
        if installed or old_moved:
            if installed:
                try:restore_owned_config(config,before,vault,permission_added)
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
    """Explicit administrator action; leaves all knowledge and backups intact."""
    if not receipt.get('permission_added'):return False
    path=Path(config)/'settings.json';settings=read(path,{})
    fs=settings.get('sandbox',{}).get('filesystem',{})
    previous=fs.get('allowWrite',[])
    fs['allowWrite']=[x for x in previous if os.path.normcase(os.path.normpath(x))!=os.path.normcase(os.path.normpath(receipt['vault']))]
    write(path,settings)
    return previous!=fs['allowWrite']
