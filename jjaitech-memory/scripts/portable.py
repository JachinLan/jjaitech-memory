"""Versioned, data-only portability and reviewed work-sharing bundles.

This module never executes archive content and never imports a supplied SQLite DB.
"""
import hashlib
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import uuid
import zipfile

SCHEMA = 'jjaitech-memory-portable/2'
MAX_BYTES = 512 * 1024 * 1024


def encode(rows):
    return ''.join(json.dumps(dict(row), ensure_ascii=False)+'\n' for row in rows).encode('utf-8')


def read_bundle(path):
    with zipfile.ZipFile(path) as z:
        info = z.infolist()
        names = [x.filename for x in info]
        if len(names)>100000 or len(names) != len(set(names)) or sum(x.file_size for x in info) > MAX_BYTES:
            raise ValueError('duplicate names or oversized bundle')
        for item in info:
            name = item.filename
            if name.startswith(('/', '\\')) or '\\' in name or '..' in Path(name).parts or ':' in name:
                raise ValueError('unsafe archive path')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('archive symlinks forbidden')
        manifest = json.loads(z.read('manifest.json').decode('utf-8'))
        if manifest.get('schema') not in (SCHEMA,'jjaitech-memory-portable/1') or manifest.get('kind') not in ('private-backup', 'work-share'):
            raise ValueError('unsupported bundle schema or kind')
        expected = manifest.get('files')
        if not isinstance(expected, dict) or set(names) != set(expected) | {'manifest.json'}:
            raise ValueError('manifest file set mismatch')
        data = {}
        for name, checksum in expected.items():
            body = z.read(name)
            if hashlib.sha256(body).hexdigest() != checksum:
                raise ValueError('bundle checksum mismatch')
            data[name] = body
    return manifest, data


def validate_rows(manifest, data, categories):
    entities = [json.loads(x) for x in data['entities.jsonl'].decode('utf-8').splitlines()]
    facts = [json.loads(x) for x in data['facts.jsonl'].decode('utf-8').splitlines()]
    if len(entities) > 100000 or len(facts) > 1000000:
        raise ValueError('too many records')
    if manifest.get('record_counts')!={'entities':len(entities),'facts':len(facts)}:
        raise ValueError('manifest record counts do not match content')
    owner=manifest.get('owner',{})
    if not isinstance(owner,dict) or not re.fullmatch(r'[a-f0-9]{32}',owner.get('owner_id','')):
        raise ValueError('missing/invalid contributor identifier')
    ids = set()
    for e in entities:
        if not isinstance(e, dict) or not re.fullmatch(r'[a-f0-9]{24}', e.get('id', '')) or e['id'] in ids:
            raise ValueError('invalid/duplicate entity ID')
        if e.get('category') not in categories or e.get('domain') not in ('Personal','Work'):
            raise ValueError('invalid entity classification')
        if not isinstance(e.get('name'), str) or not 1 <= len(e['name']) <= 160:
            raise ValueError('invalid entity name')
        aliases=json.loads(e.get('aliases','[]'))
        if not isinstance(aliases,list) or any(not isinstance(x,str) or len(x)>160 for x in aliases):
            raise ValueError('invalid aliases')
        if manifest['kind']=='work-share' and (e['domain']!='Work' or e['category']=='Personal'):
            raise ValueError('personal entity in work-sharing bundle')
        ids.add(e['id'])
    fact_ids=set()
    for f in facts:
        if not isinstance(f,dict) or not re.fullmatch(r'[a-f0-9]{64}',f.get('id','')) or f['id'] in fact_ids:
            raise ValueError('invalid/duplicate fact ID')
        if f.get('entity_id') not in ids or f.get('kind') not in ('reported','confirmed','documented','inference','ai_suggestion'):
            raise ValueError('invalid fact reference/type')
        for key,limit in [('text',2000),('evidence',2000),('session',300),('date',100),('job',100)]:
            if not isinstance(f.get(key),str) or len(f[key])>limit:
                raise ValueError('invalid fact field '+key)
        relations=json.loads(f.get('relations','[]'))
        if not isinstance(relations,list) or any(not isinstance(x,str) or len(x)>200 for x in relations):
            raise ValueError('invalid relations')
        try:dt.datetime.fromisoformat(f['date'].replace('Z','+00:00'))
        except ValueError:raise ValueError('invalid fact timestamp')
        fact_ids.add(f['id'])
    if manifest['kind']=='work-share' and set(data)-{'entities.jsonl','facts.jsonl'}:
        raise ValueError('raw/files forbidden in work-share')
    return entities,facts


def owner(memory):
    path=memory.ROOT/'.state/owner.json'
    obj=memory.jread(path,None)
    if not obj:
        obj={'owner_id':uuid.uuid4().hex,'display_name':'未设置贡献者姓名'}
        memory.jwrite(path,obj)
    return obj


def export(memory, selected_ids=None):
    """Full private backup or explicitly selected Work entities. No automatic share."""
    kind='private-backup' if selected_ids is None else 'work-share'
    with memory.dbopen() as db:
        entities=[dict(x) for x in db.execute('SELECT * FROM entities ORDER BY id')]
        if selected_ids is not None:
            if not isinstance(selected_ids,list) or not selected_ids:
                raise ValueError('explicit nonempty approved entity ID list required')
            selected=set(selected_ids)
            entities=[e for e in entities if e['id'] in selected]
            if len(entities)!=len(selected) or any(e['domain']!='Work' or e['category']=='Personal' for e in entities):
                raise ValueError('unknown/private entity selected for sharing')
        ids={e['id'] for e in entities}
        facts=[dict(x) for x in db.execute('SELECT * FROM facts ORDER BY id') if x['entity_id'] in ids]
    if kind=='work-share':
        # Never copy whole user excerpts (which may mix personal/work content),
        # local path names, local session IDs, or raw conversations into sharing.
        for f in facts:
            f['evidence']='未分发原文；须向贡献者核验'
            f['session']='source-'+memory.digest(f['session'])[:20]
            f['job']='redacted'
    data={'entities.jsonl':encode(entities),'facts.jsonl':encode(facts)}
    if kind=='private-backup':
        with memory.dbopen() as db:
            data['sources.jsonl']=encode(db.execute('SELECT * FROM sources ORDER BY id'))
            data['fact_sources.jsonl']=encode(db.execute('SELECT * FROM fact_sources ORDER BY fact_id'))
        budget=sum(map(len,data.values()))
        for prefix in [*memory.CATEGORIES,'Raw','Share']:
            for p in (memory.ROOT/prefix).rglob('*'):
                if p.is_file():
                    memory.safe(p)
                    budget += p.stat().st_size
                    if budget > MAX_BYTES:
                        raise ValueError('export exceeds 512 MiB; use a full directory backup')
                    data[p.relative_to(memory.ROOT).as_posix()]=p.read_bytes()
        for name in ['SCHEMA.md','index.md','log.md']:
            p=memory.ROOT/name
            if p.exists():
                data[name]=memory.safe(p).read_bytes()
        data['owner.json']=json.dumps(owner(memory),ensure_ascii=False).encode('utf-8')
        data['config.json']=json.dumps(memory.jread(memory.ROOT/'.state/config.json',{}),ensure_ascii=False).encode('utf-8')
        # Outstanding jobs and progress are included for audit/recovery. Restoration
        # does not auto-resume old host sessions or transmit them to a new model.
        for prefix in ['.state/jobs','.state/sessions','.state/conflicts','.state/chunks','.state/receipts']:
            for p in (memory.ROOT/prefix).glob('*'):
                if p.is_file():
                    data['recovery/'+p.relative_to(memory.ROOT/'.state').as_posix()]=memory.safe(p).read_bytes()
    if sum(map(len,data.values())) > MAX_BYTES:
        raise ValueError('export exceeds 512 MiB; use an administrator-managed full directory backup')
    manifest={'schema':SCHEMA,'kind':kind,'created_at':memory.now(),'owner':owner(memory),
              'review_required':kind=='work-share','record_counts':{'entities':len(entities),'facts':len(facts)},
              'files':{name:memory.digest(body) for name,body in data.items()}}
    path=memory.ROOT/'.state/exports'/(kind+'-'+uuid.uuid4().hex+'.zip')
    memory.safe(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.pending')
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            for name,body in data.items():z.writestr(name,body)
        read_bundle(temp)
        temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
    review=None
    if kind=='work-share':
        review=path.with_suffix('.review.md')
        memory.atomic(review,'# 共享包发送前审阅\n\n该文件对应同名 ZIP 的固定内容。未发送、未发布。请核查姓名、客户机密、价格有效期、邮件措辞和个人信息。\n\n```json\n'+
            json.dumps({'owner':manifest['owner'],'entities':entities,'facts':facts},ensure_ascii=False,indent=2)+'\n```\n')
    return {'path':str(path),'review_path':str(review) if review else None,'kind':kind,'entities':len(entities),'facts':len(facts),
            'notice':'本地文件；未发送。分享前仍须审阅事实文字中的商业机密与个人信息。'}


def restore(memory,path):
    manifest,data=read_bundle(path)
    if manifest['kind']!='private-backup':
        raise ValueError('use share-import for work-share bundles')
    entities,facts=validate_rows(manifest,data,memory.CATEGORIES)
    import sources
    source_records=[json.loads(x) for x in data.get('sources.jsonl',b'').decode('utf-8').splitlines()]
    source_ids=sources.validate_records(memory,source_records,data)
    fact_sources=[json.loads(x) for x in data.get('fact_sources.jsonl',b'').decode('utf-8').splitlines()]
    fids={f['id'] for f in facts}
    if any(r.get('fact_id') not in fids or r.get('source_id') not in source_ids for r in fact_sources):raise ValueError('invalid fact provenance')
    with memory.dbopen() as db:
        if db.execute('SELECT COUNT(*) FROM entities').fetchone()[0]:
            raise ValueError('restore target must have no entities; use a new vault')
    if any(p.is_file() for folder in [*memory.CATEGORIES,'Raw','Share'] for p in (memory.ROOT/folder).rglob('*')):
        raise ValueError('restore target contains files; use a new vault')
    # Never trust archive-supplied entity paths for future writes.
    for e in entities:
        slug=re.sub(r'[^\w\-一-龥]','-',e['name']).strip('-')[:64] or 'entity'
        e['path']=f"{e['category']}/{slug}-{e['id'][:8]}.md"
    allowed={'SCHEMA.md','index.md','log.md','owner.json','config.json','entities.jsonl','facts.jsonl','sources.jsonl','fact_sources.jsonl'}
    for name in data:
        if name not in allowed and not name.startswith(tuple(p+'/' for p in [*memory.CATEGORIES,'Raw','Share','recovery'])):
            raise ValueError('unexpected private backup file')
    cfg=memory.jread(memory.ROOT/'.state/config.json',{})
    cfg['enabled']=False
    cfg['model_processing_allowed']=False
    memory.jwrite(memory.ROOT/'.state/config.json',cfg)
    marker=memory.ROOT/'.state/restore-in-progress.json'
    memory.jwrite(marker,{'started_at':memory.now(),'bundle_sha256':memory.digest(Path(path).read_bytes())})
    # Stage file copies before SQL import. Failure is explicit, target stays a
    # separate recovery vault and the source/backup are never overwritten.
    for name,body in data.items():
        if name.startswith(tuple(prefix+'/' for prefix in [*memory.CATEGORIES,'Raw','Share'])):
            memory.atomic(memory.ROOT/name,body)
        elif name.startswith('recovery/'):
            memory.atomic(memory.ROOT/'.state/restored-recovery'/name[len('recovery/'):],body)
        elif name.endswith('.md'):
            # Preserve original manually edited pages as reference; regenerate new
            # canonical pages rather than overwriting historical manual edits.
            memory.atomic(memory.ROOT/'.state/restored-documents'/name,body)
    memory.jwrite(memory.ROOT/'.state/owner.json',json.loads(data.get('owner.json',b'{}')))
    with memory.dbopen() as db:
        db.execute('BEGIN IMMEDIATE')
        for e in entities:
            db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)',tuple(e[k] for k in ['id','category','name','aliases','domain','path']))
        for f in facts:
            db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)',tuple(f[k] for k in ['id','entity_id','text','kind','date','session','evidence','relations','job']))
        for r in source_records:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)',tuple(r[k] for k in ['id','title','original_path','snapshot_path','sha256','captured_at','session','scope','chars']))
            sources.index_passages(memory,db,r,data[r['snapshot_path']].decode('utf-8'))
        for r in fact_sources:db.execute('INSERT INTO fact_sources VALUES (?,?)',(r['fact_id'],r['source_id']))
        for e in entities:db.execute('INSERT INTO render_pending VALUES (?)',(e['id'],))
    memory.recover_rendering()
    sources.catalog(memory)
    marker.unlink()
    return {'restored_entities':len(entities),'restored_facts':len(facts),
            'enabled':False,'notice':'已恢复到独立资料库；先核对，再明确允许新客户端/模型处理。旧待办保留作恢复材料，不自动续跑。'}


def preview(memory):
    with memory.dbopen() as db:
        return [{'id':e['id'],'name':e['name'],'category':e['category'],
                 'fact_count':db.execute('SELECT COUNT(*) FROM facts WHERE entity_id=?',(e['id'],)).fetchone()[0],
                 'notice':'目录仅列前50项；选定导出后请阅读同名 review.md，未自动发送'}
                for e in db.execute("SELECT * FROM entities WHERE domain='Work' AND category!='Personal' ORDER BY name LIMIT 50")]


def share_import(memory,path):
    manifest,data=read_bundle(path)
    if manifest['kind']!='work-share':
        raise ValueError('a full private backup cannot be imported as shared work')
    entities,facts=validate_rows(manifest,data,memory.CATEGORIES)
    bundle_id=memory.digest(Path(path).read_bytes())
    folder=memory.ROOT/'Share/Incoming'/bundle_id
    # Explicit CLI import only. Normal Hooks never call this method.
    for name,body in data.items():memory.atomic(folder/name,body)
    memory.jwrite(folder/'manifest.json',manifest)
    memory.jwrite(folder/'IMPORT_NOTICE.json',{'id':bundle_id,'imported_at':memory.now(),
        'search_enabled':False,'notice':'独立保留贡献者资料；未合并个人事实库，未自动注入模型。内容需审阅，身份仅自报。'})
    return {'bundle':bundle_id,'path':str(folder),'search_enabled':False,
            'notice':'独立导入完成；不覆盖本人的同名客户和报价。当前需人工查阅/引用，团队权限检索尚未实现。'}
