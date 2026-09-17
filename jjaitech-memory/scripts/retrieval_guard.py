"""Performance guard for implicit whole-disk historical recall, not general shell policy."""
from pathlib import Path
import re
import shlex
import sources


def decision(memory,prompt,name,args):
    if not memory.retrieval_only(prompt):return None
    if name=='DeferExecuteTool':
        name=args.get('toolName','');args=args.get('params') or {}
    if memory.fast_recall(prompt) and (name in ('read_me','show_widget') or name.endswith(('__read_me','__show_widget'))):
        return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
            'permissionDecisionReason':'This turn is a simple historical fact lookup, not a request for a visual artifact. Answer concisely in plain text using the retrieved sources. Do not generate widget HTML or retry this tool. Visuals remain available when the user asks for them.'}}

    if re.search(r'全盘|整个(?:目录|主目录|电脑)|所有文件|全目录|entire|all files|recursively search',prompt,re.I):return None
    home=str(Path.home());wiki=str(memory.ROOT)
    broad=[home,home+'/Desktop',home+'/Documents',home+'/Downloads',home+'/Library',
           home+'/WorkBuddy',home+'/.workbuddy/projects',wiki+'/Raw','/var/folders','/private/var/folders','/tmp']
    normalize=lambda s:s.replace('\\','/').rstrip('/').casefold()
    requested=[]
    if name in ('Grep','Glob'):
        requested=[str(args.get('path',''))]
    elif name in ('Bash','PowerShell'):
        command=str(args.get('command',''))
        if not re.search(r'\bfind\b|\brg\b|\bgrep\b[^\n]*(?:\s-[A-Za-z]*[rR]|--recursive)|Get-ChildItem[^\n]*-Recurse',command,re.I):return None
        command=command.replace('${HOME}',home).replace('$HOME',home).replace('$env:USERPROFILE',home).replace('~/',home+'/')
        try:requested=[x.strip('\"\'') for x in shlex.split(command,posix=False)]
        except ValueError:return None
    for path in requested:
        target=next((b for b in broad if normalize(b)==normalize(path)),None)
        if target and not sources.referenced(target,[prompt]):
            return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                'permissionDecisionReason':'This is an implicit historical recall request. Do not recursively scan broad home/Raw/temp directories. Use jjaitech-memory search_memory for bounded source excerpts, read a specific cited file, or ask the user for a source. An explicit user request for this broader directory is allowed.'}}
    return None
