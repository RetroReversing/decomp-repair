"""Memory-order hypotheses supported by the measured MIPS instruction sequence."""

import re

from .integer_repair_support import IDENT, edit, integer, locals_for, view
from .pattern_repairs import close
from .repair_source_view import read

REG = r'\$\w+'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LOAD = re.compile(rf'lwc1\s+({REG}),\s*({NUM})?\(({REG})\)')
CALL = re.compile(rf'jal\s+({IDENT})')
RESET = re.compile(r'move\s+(\$s[0-7]),\s*\$zero')


def reordered_pair(source, part, rows, changed):
    if len(changed) != 2 or changed[1] != changed[0]+1:
        return None
    first,second = (rows[i] for i in changed)
    if (first[1],second[1]) != (second[2],first[2]):
        return None
    a,b = LOAD.fullmatch(first[1]),LOAD.fullmatch(second[1])
    if not a or not b or a[3] != b[3] or a[1] == b[1] or a[2] == b[2]:
        return None
    assignment = (rf'(?P<{{tag}}>{IDENT})\s*=\s*M2C_FIELD\s*\(\s*(?P<base{{tag}}>{IDENT})\s*,\s*f32\s*\*\s*,\s*'
                  rf'(?P<off{{tag}}>{NUM})\s*\)')
    pair = re.compile(r'(?:&&|\|\||[;{])\s*\(\s*(?P<first>'+assignment.format(tag='x')+r')\s*,\s*'
                      +'(?P<second>'+assignment.format(tag='y')+r')(?=\s*,)')
    floats = {name.strip() for group in re.findall(r'(?<=[;{])\s*f32\s+([^;{}]+);',part.clean)
              for name in group.split(',') if re.fullmatch(IDENT,name.strip())}
    candidates = []
    for m in pair.finditer(part.clean,part.opening+1,part.end):
        if ({m['x'],m['y']} - floats or m['x']==m['y'] or m['basex']!=m['basey']
                or m['basex'] in (m['x'],m['y'])
                or (integer(m['offx']),integer(m['offy']))!=(integer(b[2] or '0'),integer(a[2] or '0'))):
            continue
        if any(re.search(rf'&\s*{m[k]}\b',part.body) for k in ('x','y')):
            continue
        if re.search(r'/[*/]', source[m.start('first'):m.end('second')]):
            continue
        candidates.append(edit(source, [(*m.span('first'), source[slice(*m.span('second'))]),
                                        (*m.span('second'), source[slice(*m.span('first'))])]))
    return candidates[0] if len(candidates) == 1 else None


def reset_call(rows, changed):
    if len(changed) != 4 or changed[-1]-changed[0] != 4:
        return None
    window = rows[changed[0]:changed[-1]+1]
    target,prior = ([row[side] for row in window if row[side]] for side in (1,2))
    if len(target) != 3 or len(prior) != 3 or target != prior[::-1]:
        return None
    call,reset = CALL.fullmatch(prior[1]), RESET.fullmatch(prior[0])
    if not call or not reset or re.search(rf'{re.escape(reset[1])}\b',prior[2]):
        return None
    return call[1]


def reset_after_call(source, part, rows, changed):
    callee = reset_call(rows,changed)
    if not callee:
        return None
    pattern = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<reset>(?P<name>{IDENT})\s*=\s*0\s*;)'
                         rf'(?P<gap>\s+)(?P<callee>{callee})\s*\(')
    directives = re.findall(r'(?m)^[ \t]*#\s*define[^\n]*', source)
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})',
                            source[part.opening:part.end]))
    external = set(re.findall(IDENT, '\n'.join(directives)))
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        name = hit['name']
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if (not prefix or prefix[-1] not in ';{}' or name in external or callee in external
                or not any(decl['name'] == name for decl in locals_for(part))):
            continue
        end = close(part.clean,hit.end()-1)
        if not end or part.clean[end:end+1] != ';' or re.search(rf'\b{name}\b',part.clean[hit.end():end]):
            continue
        if macros & set(re.findall(IDENT,part.clean[hit.start('reset'):end+1])):
            continue
        statement = source[hit.start('callee'):end+1]
        gap = source[slice(*hit.span('gap'))]
        if re.search(r'/[*/]|#',gap):
            continue
        return edit(source,[(hit.start('reset'),end+1,statement+gap+source[slice(*hit.span('reset'))])])
    return None


def variants(source, name, rows):
    changed = [i for i,(mark,_,_) in enumerate(rows) if mark != ' ']
    if len(changed) not in (2,4):
        return []
    part = view(source,name)
    if part is None:
        if (part := read(source,name)) and (candidate := reset_after_call(source,part,rows,changed)):
            return [('measured_call_reset_order',candidate)]
        return []
    if candidate := reordered_pair(source,part,rows,changed):
        return [('measured_comma_load_order',candidate)]
    if candidate := reset_after_call(source,part,rows,changed):
        return [('measured_call_reset_order',candidate)]
    return []
