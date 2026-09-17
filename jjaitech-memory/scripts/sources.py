"""Bounded local indexing of explicitly user-referenced Read results.
Never follows a new filesystem path or treats tool/source text as instructions.
"""
import json
from pathlib import Path, PureWindowsPath
import re
import time

MAX_SOURCE_CHARS=2_000_000
MAX_CAPTURE_TRANSCRIPT=32*1024*1024


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sources (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, original_path TEXT NOT NULL,
      snapshot_path TEXT NOT NULL, sha256 TEXT NOT NULL, captured_at TEXT NOT NULL,
      session TEXT NOT NULL, scope TEXT NOT NULL, chars INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS source_observations (
      source_id TEXT NOT NULL, session TEXT NOT NULL, PRIMARY KEY(source_id,session));
    CREATE TABLE IF NOT EXISTS fact_sources (fact_id TEXT PRIMARY KEY, source_id TEXT NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS source_lookup USING fts5(source_id UNINDEXED, offset UNINDEXED, tokens, body UNINDEXED);
    ''')


def content_text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return '\n'.join(content_text(x) for x in value)
    if isinstance(value,dict):
        if isinstance(value.get('text'),str):return value['text']
        if value.get('type') in ('tool_result','text','input_text','output_text') or 'content' in value:
            return content_text(value.get('content',''))
        if isinstance(value.get('file'),dict):return content_text(value['file'])
    return ''


def normalized(path):
    return path.replace('\\','/').rstrip('/').casefold() if re.match(r'^[A-Za-z]:[\\/]',path) else path.replace('\\','/').rstrip('/')


def referenced(path, prompts):
    # Explicit user supplied absolute path, from text or host's user_references.
    # Never authorize a path merely because an assistant/tool result mentions it.
    path=normalized(path)
    pattern=re.compile(r'(?<![A-Za-z0-9_./:\\-])'+re.escape(path)+r'(?=$|[\s\"\'<>，。;,)\]}}])')
    return any(pattern.search(normalized(prompt)) for prompt in prompts)


def extract(raw, wiki_root):
    prompts=[];calls={};maintenance=False;results=[]
    for line in raw.splitlines():
        try:o=json.loads(line)
        except (ValueError,TypeError):continue
        msg=o.get('message',o);role=msg.get('role',o.get('type')) if isinstance(msg,dict) else ''
        meta=o.get('isMeta') or o.get('providerData',{}).get('isMeta')
        blocks=msg.get('content',[]) if isinstance(msg,dict) else []
        if role=='user' and meta:
            maintenance=True;continue
        if role=='user' and not meta:
            # Tool-result messages are not authored user text.
            text=content_text([b for b in blocks if isinstance(b,dict) and b.get('type') in ('text','input_text')]) if isinstance(blocks,list) else content_text(blocks)
            if text.startswith('Stop hook feedback:'):maintenance=True;continue
            if text:prompts.append(text);maintenance=False
        if maintenance:continue
        tool_calls=[];tool_results=[]
        if o.get('type')=='function_call':
            try:args=json.loads(o.get('arguments','{}'))
            except (ValueError,TypeError):args={}
            tool_calls.append((o.get('callId'),o.get('name'),args))
        if role=='assistant' and isinstance(blocks,list):
            tool_calls.extend((b.get('id'),b.get('name'),b.get('input',{})) for b in blocks if isinstance(b,dict) and b.get('type')=='tool_use')
        for call_id,name,args in tool_calls:
            if name!='Read' or not isinstance(args,dict) or not isinstance(call_id,str) or not call_id:continue
            path=args.get('file_path','')
            if not isinstance(path,str) or not path or len(path)>4096:continue
            if not (path.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:[\\/]',path)):continue
            norm=normalized(path)
            # Recalled Wiki text and internal host memory are not new source input.
            if norm.startswith(normalized(str(wiki_root))+'/') or '/.workbuddy/' in norm or '/.codebuddy/' in norm:continue
            if referenced(path,prompts):calls[call_id]=path
        if o.get('type')=='function_call_result':
            tool_results.append((o.get('callId'),o.get('output'),o.get('status')=='failed'))
        if isinstance(blocks,list):
            tool_results.extend((b.get('tool_use_id'),b.get('content'),b.get('is_error',False)) for b in blocks if isinstance(b,dict) and b.get('type')=='tool_result')
        for call_id,output,error in tool_results:
            if error or call_id not in calls:continue
            text=content_text(output)
            text=re.sub(r'(?m)^[ \t]*\d+[→\t]','',text).replace('\r\n','\n').strip()
            if not text or text.startswith(('Error:','File does not exist','Permission denied')):continue
            results.append({'path':calls.pop(call_id),'text':text,'scope':'read_excerpt'})
    return results


def index_document(memory, item, sid):
    text=item['text'];path=item['path']
    if len(text)>MAX_SOURCE_CHARS:
        memory.log('source_capture_deferred',sid,reason='source_excerpt_over_2m_chars')
        return None
    hashed=memory.digest(text);source_id=memory.digest(normalized(path)+'|'+hashed)
    snapshot=f'Raw/Sources/{source_id}.txt'
    title=(PureWindowsPath(path).name if re.match(r'^[A-Za-z]:',path) else Path(path).name)[:200]
    with memory.dbopen() as db:
        known=db.execute('SELECT 1 FROM sources WHERE id=?',(source_id,)).fetchone()
        if known:
            db.execute('INSERT OR IGNORE INTO source_observations VALUES (?,?)',(source_id,sid))
            return source_id
    memory.atomic(memory.ROOT/snapshot,text)
    record={'id':source_id,'title':title,'original_path':path,'snapshot_path':snapshot,'sha256':hashed,
            'captured_at':memory.now(),'session':sid,'scope':item.get('scope','read_excerpt'),'chars':len(text)}
    memory.jwrite(memory.ROOT/'Raw/Sources'/(source_id+'.json'),record)
    with memory.dbopen() as db:
        db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?,?,?)',tuple(record[k] for k in ['id','title','original_path','snapshot_path','sha256','captured_at','session','scope','chars']))
        db.execute('INSERT OR IGNORE INTO source_observations VALUES (?,?)',(source_id,sid))
        index_passages(memory,db,record,text)
    memory.log('source_indexed',sid,source_id=source_id,chars=len(text))
    return source_id


def redact_credentials(text):
    text=re.sub(r'(?im)^\s*(?:password|passwd|api[_-]?key|access[_-]?token|secret|密码|密钥)\s*[:=：].*$', '[credential redacted]', text)
    text=re.sub(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._~-]{20,})', '[credential redacted]', text)
    return text


def index_passages(memory,db,record,text):
    db.execute('DELETE FROM source_lookup WHERE source_id=?',(record['id'],))
    for offset in range(0,len(text),1400):
        body=redact_credentials(text[offset:offset+1800])
        db.execute('INSERT INTO source_lookup VALUES (?,?,?,?)',
            (record['id'],offset,' '.join(memory.tokens(record['title']+' '+body)),body))


def capture(memory,raw,sid):
    if len(raw)>MAX_CAPTURE_TRANSCRIPT:
        memory.log('source_capture_deferred',sid,reason='transcript_over_32m');return []
    started=time.monotonic();ids=[]
    for item in extract(raw.decode('utf-8',errors='replace') if isinstance(raw,bytes) else raw,memory.ROOT):
        if time.monotonic()-started>5:
            memory.log('source_capture_deferred',sid,reason='capture_time_budget');break
        key=index_document(memory,item,sid)
        if key and key not in ids:ids.append(key)
    if ids:catalog(memory)
    return ids


def catalog(memory):
    with memory.dbopen() as db:
        records=db.execute('SELECT * FROM sources ORDER BY captured_at DESC LIMIT 200').fetchall()
        lines=['# 已归档资料来源','','以下是读取过的资料片段，不等于用户本人确认；完整覆盖范围以实际Read结果为准。','']
        for r in records:lines.append(f"- [{memory.md(r['title'])}]({r['snapshot_path']}) · {r['captured_at']} · source session: {r['session']}")
        memory.write_generated(db,'sources.md','\n'.join(lines)+'\n')


def search(memory,query,budget=4500,limit=3):
    terms=memory.tokens(query)[:80]
    if not terms or budget<200:return []
    expression=' OR '.join('"'+t+'"' for t in terms)
    with memory.dbopen() as db:
        rows=db.execute('SELECT source_id,offset,body FROM source_lookup WHERE source_lookup MATCH ? ORDER BY rank LIMIT 20',(expression,)).fetchall()
        out=[];seen=set()
        for row in rows:
            key=memory.digest(row['body'])
            if key in seen:continue
            seen.add(key)
            r=db.execute('SELECT * FROM sources WHERE id=?',(row['source_id'],)).fetchone()
            if not r:continue
            text=row['body'][:min(1800,budget)]
            out.append({'type':'document_excerpt','source_id':r['id'],'title':r['title'],'path':r['snapshot_path'],
                        'source_session':r['session'],'captured_at':r['captured_at'],'scope':r['scope'],
                        'offset':row['offset'],'text':text,'status':'文件记载，未作独立核验；captured_at是归档时间，不是业务发生日期'})
            budget-=len(text)
            if len(out)>=limit or budget<200:break
    return out


def pending_messages(memory,ids,completed):
    messages=[]
    with memory.dbopen() as db:
        for key in ids:
            if key in completed:continue
            row=db.execute('SELECT * FROM sources WHERE id=?',(key,)).fetchone()
            if not row:continue
            text=memory.safe(memory.ROOT/row['snapshot_path']).read_text(encoding='utf-8')
            # The full read excerpt stays indexed; writer sees at most 12k per doc.
            messages.append({'role':'source','source_id':key,'title':row['title'],'text':redact_credentials(text[:12000])})
    return messages


def validate_records(memory,records,files):
    seen=set()
    for r in records:
        if not isinstance(r,dict) or not re.fullmatch(r'[a-f0-9]{64}',r.get('id','')) or r['id'] in seen:raise ValueError('invalid source id')
        expected='Raw/Sources/'+r['id']+'.txt'
        if r.get('snapshot_path')!=expected or expected not in files:raise ValueError('missing/unsafe source snapshot')
        body=files[expected].decode('utf-8')
        if len(body)>MAX_SOURCE_CHARS or len(body)!=r.get('chars') or memory.digest(body)!=r.get('sha256'):raise ValueError('source snapshot integrity failed')
        for k,limit in [('title',200),('original_path',4096),('session',300),('captured_at',100),('scope',50)]:
            if not isinstance(r.get(k),str) or len(r[k])>limit:raise ValueError('invalid source metadata')
        seen.add(r['id'])
    return seen
