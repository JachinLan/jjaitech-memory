"""Deterministic receipts, bounded preference coverage and contact identity helpers."""
import json,re


def preference_clauses(job):
    out=[]
    for message in job['messages']:
        if message['role']!='user':continue
        text=message['text']
        # Do not override an explicit opt-out or turn quoted examples into facts.
        if re.search(r'不要(?:保存|记住|记录)|别(?:保存|记)|do not (?:save|remember)|例如|比如|假如|假设|[「」“”"]',text,re.I):continue
        for match in re.finditer(r'(?:我(?:个人)?(?:长期|一直)(?:喜欢|不喝|习惯)|(?:我)?(?:写)?工作邮件(?:长期)?习惯)([^。！？\n，；;]{2,100})',text):
            clause=match.group(0);key=match.group(1).strip()
            if text[match.end():match.end()+1] in ('?','？') or key.endswith(('吗','呢')):continue
            if re.search(r'密码|编号|token|api.?key|cookie|例如|假如|如果|比如|[?？]',clause,re.I):continue
            out.append({'evidence':clause,'key':key,'domain':'Work' if '工作邮件' in clause else 'Personal'})
    return out[:8]


def check_coverage(job,entities):
    if job.get('contract_version',0)<4:return
    missing=[]
    for clause in preference_clauses(job):
        covered=any(e.get('domain')==clause['domain'] and any(clause['key'] in f.get('evidence','') for f in e.get('facts',[])) for e in entities)
        if not covered:missing.append(clause['evidence'])
    if missing:raise ValueError('Ordinary preference omitted: '+ ' / '.join(missing)[:160]+'. Save the ordinary preference separately from private identifiers; never discard the entire personal/work clause. If uncertain, defer for review.')


def contact_name(entity,corpus,contract):
    if entity.get('category')!='Contacts' or contract<4:return entity['name']
    person=entity.get('person_name');org=entity.get('organization','')
    if not isinstance(person,str) or not person.strip() or len(person)>80 or not isinstance(org,str) or len(org)>100:
        raise ValueError('Contacts requires person_name and organization when known. Use stable person/company identity; put job title in dated facts.')
    if person not in corpus or (org and org not in corpus):raise ValueError('Contact person_name/organization must occur in current evidence. Never invent identity.')
    if '\n' in person+org:raise ValueError('Invalid contact identity')
    return person.strip()+('（'+org.strip()+'）' if org else '')


def matching_contact(row,e,corpus):
    # Upgrades old titles only when both exact person and organization are present.
    # Never merge two companies merely because aliases contain the same first name.
    person=e.get('person_name');org=e.get('organization')
    if not person or not org:return False
    labels=[row['name'],*json.loads(row['aliases'])]
    return any(label==e['name'] or bool(re.fullmatch(re.escape(person)+r'[（(]'+re.escape(org)+r'(?:[\s /·—-]+[^（）()]*)?[）)]',label)) for label in labels)


def receipt(memory,sid):
    state=memory.jread(memory.statepath(sid),{})
    job_id=state.get('pending_job') or state.get('last_writer_job')
    job=memory.jread(memory.ROOT/'.state/jobs'/(job_id+'.json'),{}) if job_id else {}
    with memory.dbopen() as db:
        committed=db.execute('SELECT payload FROM applied_jobs WHERE id=?',(job_id,)).fetchone() if job_id else None
        count=db.execute('SELECT count(*) FROM facts WHERE job=?',(job_id,)).fetchone()[0] if job_id else 0
        pending_pages=db.execute('SELECT count(*) FROM render_pending').fetchone()[0]
    if committed:job=json.loads(committed[0])
    raw=memory.ROOT/'Raw'/(memory.digest(sid)+'.meta.json');meta=memory.jread(raw,{})
    current=job.get('generation')==state.get('generation')
    status=('facts_saved' if count else job.get('structured_status','no_new_facts')) if committed and current else ('needs_review' if job.get('needs_review') else 'pending') if job and not committed else 'archive_only'
    if status=='facts':status='no_new_facts'
    return {'page_updates_pending':pending_pages,'session':sid,'updated_at':memory.now(),'generation':state.get('generation'),
            'raw_archived':bool(meta),'raw_bytes':meta.get('bytes'),
            'structured_status':status,'facts_in_last_job':count if committed and current else 0,
            'job_id':job_id,'last_failure':job.get('last_failure') if not committed else None,
            'notice':'Raw保留原始对话；未进入实体记忆不等于未保存或已删除。状态不证明事实完整或语义正确。'}


def save_receipt(memory,sid):
    r=receipt(memory,sid)
    memory.jwrite(memory.ROOT/'.state/receipts'/(memory.digest(sid)+'.json'),r)
    # Dedicated generated status file; no personal facts in this dashboard.
    labels={'facts_saved':'重点事实已整理','no_new_facts':'本轮未提取新事实','source_only':'来源已索引，未整理实体','needs_review':'整理待复核','pending':'整理尚未完成','archive_only':'原文归档；本轮无整理提交'}
    text='# 记忆保存状态（插件核验）\n\n'+f"更新时间：{r['updated_at']}\n\n- source session：{sid}\n- 原文：{'已归档' if r['raw_archived'] else '尚未归档'}\n- 整理：{labels.get(r['structured_status'],r['structured_status'])}\n- 本轮写入事实：{r['facts_in_last_job']}\n\n"+r['notice']+'\n\n历史状态在 .state/receipts；完整诊断使用 doctor。\n'
    memory.atomic(memory.ROOT/'.state/MEMORY_STATUS.md',text)
    return r


def post_writer(memory,p,state):
    name=p.get('tool_name');args=p.get('tool_input') or {}
    if name=='DeferExecuteTool':name=args.get('toolName');args=args.get('params') or {}
    if isinstance(name,str):name=name.replace('mcp__jjaitech_memory__','mcp__jjaitech-memory__')
    if name not in ('mcp__jjaitech-memory__write_memory','mcp__jjaitech-memory__defer_memory'):return None
    jid=args.get('job_id');sid=p['session_id']
    if not isinstance(jid,str) or not re.fullmatch('[a-f0-9]{32}',jid):return None
    job=memory.jread(memory.ROOT/'.state/jobs'/(jid+'.json'),{})
    if job.get('session')!=sid or job.get('generation')!=state.get('generation') or state.get('issued_generation')!=state.get('generation'):return None
    with memory.dbopen() as db:committed=db.execute('SELECT 1 FROM applied_jobs WHERE id=?',(jid,)).fetchone()
    if not committed and not job.get('needs_review'):return None # one correction remains
    if state.get('writer_finalized_job')==jid:return None
    memory.archive(p) # best available transcript; SessionEnd refreshes the full copy
    r=save_receipt(memory,sid)
    state=memory.jread(memory.statepath(sid),state);state['writer_finalized_job']=jid;memory.jwrite(memory.statepath(sid),state)
    label=f"原文已归档；重点事实已整理（{r['facts_in_last_job']}条）" if committed and r['facts_in_last_job'] else '原文已归档；'+('本轮未新增实体事实' if committed else '整理待复核，未完成')
    if r['page_updates_pending']:label+='；部分阅读页待刷新'
    memory.log('writer_finalized_locally',sid,job=jid,committed=bool(committed))
    return {'suppressOutput':True,'systemMessage':'jjaitech-memory：'+label+'。详见 AI-Wiki/.state/MEMORY_STATUS.md。',
            'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':'Local storage verification: '+label+'. The user task was already answered. Maintenance has ended; call no further tools. Finish with only 已处理。 Do not restate facts or claim Raw was not saved.'}}
