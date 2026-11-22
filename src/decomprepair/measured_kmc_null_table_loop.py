"""Recover a counted table loop when the increment was duplicated into both arms."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .narrow_store_repairs import declared
from .operand_lifetime_repairs import _escaped
from .target_memory_repairs import _statement

FIELD = rf'M2C_FIELD\(\s*(?P<obj>{IDENT})\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\)'
INDEXED = rf'M2C_FIELD\(\s*\(\s*\(\s*(?P=idx)\s*\*\s*4\s*\)\s*\+\s*(?P=table)\s*\)\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\)'
LOOP = re.compile(
    rf'(?P<idx>{IDENT})\s*=\s*0\s*;\s*do\s*{{\s*'
    rf'(?P<table>{IDENT})\s*=\s*{FIELD}\s*;\s*'
    rf'if\s*\(\s*(?P=table)\s*==\s*0\s*\)\s*{{\s*(?P<nullinc>(?P=idx)\s*\+=\s*1\s*;)\s*}}\s*else\s*{{\s*'
    rf'(?P<value>{IDENT})\s*=\s*{INDEXED}\s*;\s*(?P<valueinc>(?P=idx)\s*\+=\s*1\s*;)\s*'
    rf'if\s*\(\s*(?P=value)\s*!=\s*0\s*\)\s*{{\s*(?P<call>{IDENT})\s*\(\s*(?P=value)\s*\)\s*;\s*}}\s*}}\s*}}\s*'
    rf'while\s*\(\s*(?P=idx)\s*<\s*(?P<limit>{NUMBER})\s*\)\s*;'
)


def variants(source,name,header,rows):
    target = ' '.join(left for _,left,_ in rows if left)
    candidate = ' '.join(right for _,_,right in rows if right)
    if not (re.search(r'\bbeql\s+\$\w+,\s*\$zero,',target)
            and re.search(r'\bbnez\s+\$\w+,',candidate)
            and re.search(r'\bj\s+\S+',candidate)):
        return []
    part = view(source,name)
    if not part or re.search(r'\b(?:setjmp|longjmp|asm|__asm__)\b',part.body):
        return []
    definitions = re.findall(r'^\s*#\s*define\s+('+IDENT+r')([^\n]*)',_blank(header+'\n'+source),re.M)
    for hit in LOOP.finditer(part.clean,part.opening+1,part.end-1):
        idx = hit['idx']
        roles = (idx,hit['table'],hit['value'],hit['obj'])
        if (not _statement(part,hit.start()) or len(set(roles))!=len(roles) or
                declared(part,idx,hit.start(),header)!=('s32','') or _escaped(part.body,idx) or
                not 0<integer(hit['limit'])<=0x7fffffff or
                re.search(rf'\b{re.escape(hit["call"])}\s*\([^;{{}}]*\)\s*\{{',part.body) or
                any(macro in {idx,hit['call']} or re.search(rf'\b{re.escape(idx)}\b',body)
                    for macro,body in definitions)):
            continue
        opening = part.clean.index('{',hit.start(),hit.start('nullinc'))
        ending = part.clean.rindex('}',hit.end('valueinc'),hit.end())
        prefix = f'for ({idx} = 0; {idx} < {hit["limit"]}; {idx}++) '
        replacement = edit(source[opening:ending+1],[(hit.start(k)-opening,hit.end(k)-opening,'')
                                                    for k in ('nullinc','valueinc')])
        return [('counted_null_table_for',edit(source,[(hit.start(),hit.end(),prefix+replacement)]))]
    return []
