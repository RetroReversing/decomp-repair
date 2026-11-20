"""Change a local's lifetime only at a matching MIPS load or return boundary."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .pattern_repairs import close

REG = r'\$\w+'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LOAD = re.compile(rf'lw\s+({REG}),\s*({NUMBER})?\(({REG})\)')
BRANCH = re.compile(rf'beqz\s+({REG}),\s*(\S+)')


def return_load(rows):
    """The game's last load already writes the result register."""
    if len(rows) < 3 or tuple(rows[-2]) != (' ','jr $ra','jr $ra'):
        return None
    mark,target,candidate = rows[-1]
    move = re.fullmatch(rf'move\s+\$v0,\s*({REG})',candidate)
    a,b = (LOAD.fullmatch(line) for line in rows[-3][1:])
    if (mark != ' ' and target == 'nop' and move and a and b and a[1] == '$v0'
            and b[1] != a[1] and b[1] == move[1] and a[2] == b[2]):
        return integer(a[2] or '0')
    return None


def direct_load_return(source, name, part, rows):
    offset = return_load(rows)
    if offset is None:
        return None
    result = re.search(rf'\b(?P<type>s32|int)\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*$',
                       part.clean[:part.opening])
    if not result:
        return None
    tail = re.search(rf'\breturn\s+(?P<value>{IDENT})\s*;\s*}}?\s*$',part.body)
    if not tail:
        return None
    local = tail['value']
    uses = list(re.finditer(rf'\b{local}\b',part.body))
    typ = result['type']
    if len(uses) != 3 or not re.search(rf'\b{typ}\s+{local}\s*=\s*0\s*;',part.body):
        return None
    guarded = re.compile(rf'\bif\s*\(\s*(?P<ptr>{IDENT})\s*\)\s*(?P<write>{local}\s*=)\s*'
                         rf'\*\s*\(\s*{typ}\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*'
                         rf'(?P=ptr)\s*\+\s*(?P<offset>{NUMBER})\s*\)\s*;(?=[\s}}]*return\s+{local}\s*;)')
    hit = guarded.search(part.body)
    if not hit or integer(hit['offset']) != offset:
        return None
    start = part.opening+1
    a,b = hit.span('write')
    c,d = tail.span('value')
    if re.search(r'/[*/]',source[start+a:start+b]):
        return None
    return edit(source,[(start+a,start+b,'return'),(start+c,start+d,'0')])


def alias_gap(rows):
    """Trace a field from the target's load through its null check and call-register move."""
    changes = [index for index,(mark,_,_) in enumerate(rows) if mark != ' ']
    if len(changes) != 3:
        return None
    i,j,k = changes
    if (j,k) != (i+1,i+2) or k+1 >= len(rows):
        return None
    a,b = (LOAD.fullmatch(text) for text in rows[i][1:])
    left,right = (BRANCH.fullmatch(text) for text in rows[j][1:])
    downstream = LOAD.fullmatch(rows[k+1][1])
    if (not all((a,b,left,right,downstream)) or a[1] == '$a0' or b[1] != '$a0'
            or a.groups()[1:] != b.groups()[1:] or left.groups() != (a[1],right[2]) or right[1] != '$a0'
            or tuple(rows[k][1:]) != (f'move $a0, {a[1]}','nop')
            or downstream[3] != '$a0' or rows[k+1][1] != rows[k+1][2]):
        return None
    return integer(a[2] or '0'),integer(downstream[2] or '0')


def null_guard_alias(source, part, rows):
    gap = alias_gap(rows)
    alias = '__repair_subobject'
    if not gap or alias in part.clean:
        return None
    guard = re.compile(rf'\b(?P<temp>{IDENT})\s*=\s*M2C_FIELD\s*\(\s*{IDENT}\s*,\s*void\s*\*\s*\*\s*,\s*'
                       rf'(?P<offset>{NUMBER})\s*\)\s*;\s*if\s*\(\s*(?P=temp)\s*!=\s*NULL\s*\)\s*{{')
    for hit in guard.finditer(part.clean,part.opening+1,part.end):
        temp = hit['temp']
        if integer(hit['offset']) != gap[0] or not re.search(rf'\bvoid\s*\*\s*{temp}\s*;',part.body):
            continue
        end = close(part.clean,hit.end()-1,'{','}')
        if not end:
            continue
        uses = list(re.compile(rf'\b{temp}\b').finditer(part.clean,hit.end(),end-1))
        bases = list(re.compile(rf'\bM2C_FIELD\s*\(\s*({temp})\s*,\s*[^,();]+,\s*({NUMBER})\s*\)')
                     .finditer(part.clean,hit.end(),end-1))
        if (not 1 <= len(uses) == len(bases) <= 6
                or integer(bases[0][2]) != gap[1]):
            continue
        return edit(source,[(hit.end(),hit.end(),f'\nvoid *{alias} = {temp};'),
                            *((m.start(1),m.end(1),alias) for m in bases)])
    return None


def variants(source, name, rows):
    part = view(source,name)
    if part is None:
        return []
    if candidate := direct_load_return(source,name,part,rows):
        return [('measured_direct_load_return',candidate)]
    if candidate := null_guard_alias(source,part,rows):
        return [('measured_null_guard_alias',candidate)]
    return []
