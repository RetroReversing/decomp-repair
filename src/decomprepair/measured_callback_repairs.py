"""Try a candidate-local no-argument callback when the target omits record setup."""

import re

from .integer_repair_support import IDENT, edit, integer, view

REG = r'\$\w+'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LOAD = re.compile(rf'lw\s+({REG}),\s*({NUMBER})?\(({REG})\)')
BRANCH = re.compile(rf'beqz\s+({REG}),\s*(\S+)')
ARGUMENT = re.compile(r'\$a[0-3]\b')
OBJECT = r'void\s*\*'
CALLBACK = r'void\s*\(\s*\*'


def field_offsets(rows):
    """Isolate the same record and callback loads, with no target call argument."""
    changed = [i for i,(mark,_,_) in enumerate(rows) if mark != ' ']
    if len(changed) != 3:
        return None
    i,j,k = changed
    if (j != i+1 or k != i+3 or i < 2 or i+7 >= len(rows)
            or any(rows[index][0] != 'r' for index in changed)):
        return None
    target, candidate = ([row[side] for row in rows] for side in (1,2))
    record, old_record = LOAD.fullmatch(target[i]), LOAD.fullmatch(candidate[i])
    guard, old_guard = BRANCH.fullmatch(target[j]), BRANCH.fullmatch(candidate[j])
    callback, old_callback = LOAD.fullmatch(target[k]), LOAD.fullmatch(candidate[k])
    if not all((record,old_record,guard,old_guard,callback,old_callback)):
        return None
    if (old_record[1] != '$a0' or ARGUMENT.fullmatch(record[1]) or record.groups()[1:] != old_record.groups()[1:]
            or guard.groups() != (record[1],old_guard[2]) or old_guard[1] != old_record[1]
            or callback.groups() != (old_callback[1],old_callback[2],record[1]) or old_callback[3] != old_record[1]):
        return None
    check = BRANCH.fullmatch(target[k+1])
    tail = ['nop', f'jalr {callback[1]}', 'nop']
    if not check or check[1] != callback[1] or target[k+2:k+5] != tail or target[k+1:k+5] != candidate[k+1:k+5]:
        return None
    prior = next((p for p in range(i-2,max(-1,i-9),-1) if re.fullmatch(rf'jal\s+{IDENT}', target[p])),None)
    if prior is None or target[prior] != candidate[prior]:
        return None
    setup = target[prior+1:k+5]
    if any(ARGUMENT.search(text) for text in setup):
        return None
    return integer(record[2] or '0'), integer(callback[2] or '0')


def variants(source, name, rows):
    offsets = field_offsets(rows)
    part = view(source,name) if offsets is not None else None
    if part is None or re.search(r'\b(?:volatile|asm|__asm__)\b',part.body):
        return []
    declarations = re.compile(rf'{CALLBACK}\s*(?P<callback>{IDENT})\s*\)\s*\(\s*(?P<formal>{OBJECT})\s*\)\s*;')
    for decl in declarations.finditer(part.clean,part.opening+1,part.end):
        callback = decl['callback']
        uses = list(re.finditer(rf'\b{callback}\b',part.body))
        if len(uses) != 4:
            continue
        assignment = re.compile(rf'\b{callback}\s*=\s*M2C_FIELD\s*\(\s*(?P<record>{IDENT})\s*,\s*'
                                rf'{CALLBACK}\s*\*\s*\)\s*\(\s*(?P<formal>{OBJECT})\s*\)\s*,\s*'
                                rf'(?P<offset>{NUMBER})\s*\)\s*;')
        site = assignment.search(part.clean,decl.end(),part.end)
        if not site or integer(site['offset']) != offsets[1]:
            continue
        record = site['record']
        condition = re.compile(rf'\s*if\s*\(\s*{callback}\s*!=\s*NULL\s*\)\s*'
                               rf'{callback}\s*\(\s*(?P<arg>{record})\s*\)\s*;')
        call = condition.match(part.clean,site.end(),part.end)
        record_load = re.compile(rf'\b{record}\s*=\s*M2C_FIELD\s*\(\s*{IDENT}\s*,\s*'
                                 rf'void\s*\*\s*\*\s*,\s*({NUMBER})\s*\)\s*;')
        loads = list(record_load.finditer(part.clean,decl.end(),site.start()))
        if not call or len(loads) != 1 or integer(loads[0][1]) != offsets[0]:
            continue
        patches = [(*decl.span('formal'),'void'),(*site.span('formal'),'void'),(*call.span('arg'),'')]
        if any(re.search(r'/[*/]',source[a:b]) for a,b,_ in patches):
            continue
        return [('measured_callback_without_record',edit(source,patches))]
    return []
