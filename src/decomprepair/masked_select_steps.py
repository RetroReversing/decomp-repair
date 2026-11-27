"""A select written as one expression (`c = (u8) -(x != 0xFF) | 0x60;`) written step by step into the same local, and a
loaded narrow value re-narrowed in a call loop.

Found on an 824-instruction N64 menu drawer (KMC GCC 2.7.2, -O1, exact judge). The target computes each colour select
entirely in the argument register it is passed in (`xori a3; sltu a3; negu a3; andi a3; ori a3`), while the one-expression
spelling puts the first steps in a temporary. Writing every step into the same local keeps it in that register:

    c = x ^ 0xFF; c = c != 0; c = -c; c = (u8) c; c |= 0x60;         /* `x != 0xFF` */
    c = f; c &= 0x1000; c = c == 0; c = -c; c = (u8) c; c |= 0x7F;   /* `(f & 0x1000) == 0` */

The same function also needed a loop's loop-invariant table address NOT hoisted: loop.c moves it only while
`threshold * savings * lifetime >= insn_count`, so one more RTL instruction in the loop that costs nothing in the final
code keeps it. A value loaded from a `u16` or `u8` table into a wide local, re-narrowed right after the load
(`v = (u16) v;`), is such an instruction and changes no value. (With the steps: 440 -> 0.)"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('masked_select_steps', 'loop_narrow_self_reassign')
MAX_SITES = 6

SELECT = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<out>{IDENT})\s*=\s*\(\s*u8\s*\)\s*-\s*\(')
TAIL = re.compile(r'\s*\|\s*(?P<bits>0[xX][0-9a-fA-F]+|\d+)\s*;')
COMPARE = re.compile(r'^(?P<left>.+?)\s*(?P<op>==|!=)\s*(?P<right>0[xX][0-9a-fA-F]+|\d+)$', re.S)
MASKED = re.compile(r'^\(\s*(?P<value>[^()&|]+(?:\[[^\[\]]*(?:\[[^\[\]]*\])?[^\[\]]*\])?)\s*&\s*'
                    r'(?P<mask>0[xX][0-9a-fA-F]+|\d+)\s*\)$')
LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')
WIDE = r'(?:s32|u32|int|unsigned(?:\s+int)?)'


def _wide(clean, name):
    return re.search(rf'\b{WIDE}\s+{re.escape(name)}\s*[;=]', clean) is not None


def _steps(out, condition):
    compare = COMPARE.match(condition.strip())
    if not compare:
        return None
    left, op, right = compare['left'].strip(), compare['op'], compare['right']
    masked = MASKED.match(left)
    if int(right, 0) == 0:
        first = ([f'{out} = {masked["value"].strip()};', f'{out} &= {masked["mask"]};'] if masked
                 else [f'{out} = {left};'])
    else:
        first = [f'{out} = {left} ^ {right};']
    return first + [f'{out} = {out} {op} 0;', f'{out} = -{out};', f'{out} = (u8) {out};']


def _selects(source, part):
    found = []
    for hit in SELECT.finditer(part.clean, part.opening, part.end):
        opening = hit.end() - 1
        closing = close(part.clean, opening, '(', ')')
        if not closing or not _wide(part.clean, hit['out']):
            continue
        closing = closing if part.clean[closing - 1] == ')' else closing + 1
        tail = TAIL.match(part.clean, closing)
        if not tail:
            continue
        steps = _steps(hit['out'], source[opening + 1:closing - 1])
        if steps is None or re.search(rf'\b{hit["out"]}\b', part.clean[opening:closing]):
            continue
        steps.append(f'{hit["out"]} |= {tail["bits"]};')
        found.append((hit.start(), tail.end(), hit['lead'] + ('\n' + hit['lead']).join(steps)))
    return found


def _call_loops(part):
    """The braced loop bodies that call something, as (start, end) offsets."""
    for loop in LOOP.finditer(part.clean, part.opening, part.end):
        brace = loop.end() - 1
        if part.clean[brace] != '{':
            header = close(part.clean, brace, '(', ')')
            if not header:
                continue
            brace = part.clean.find('{', header - 1, header + 4)
            if brace < 0:
                continue
        end = close(part.clean, brace, '{', '}')
        if end and re.search(rf'\b(?!if\b|for\b|while\b|switch\b){IDENT}\s*\(', part.clean[brace:end]):
            yield brace, end


def _narrows(source, part, header):
    context = source + '\n' + (header or '')
    found = {}
    for start, end in _call_loops(part):
        for load in re.finditer(rf'(?m)^(?P<lead>[ \t]*)(?P<out>{IDENT})\s*=\s*(?P<table>{IDENT})\s*\[[^;{{}}]*\]\s*;',
                                part.clean[:end]):
            if load.start() < start or not _wide(part.clean, load['out']):
                continue
            width = re.search(rf'\bextern\s+(?P<type>u8|u16)\s+{load["table"]}\s*\[', context)
            if width:
                found[load.end()] = (load.end(), load.end(),
                                     f'\n{load["lead"]}{load["out"]} = ({width["type"]}) {load["out"]};')
    return [found[at] for at in sorted(found)]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    selects = _selects(source, part)[:MAX_SITES]
    narrows = _narrows(source, part, header)[:MAX_SITES]
    out = []
    if selects:
        out.append(('masked_select_steps', edit(source, selects)))
        if len(selects) > 1:
            out += [('masked_select_steps', edit(source, [site])) for site in selects]
    for site in narrows:
        out.append(('loop_narrow_self_reassign', edit(source, [site])))
        if selects:
            out.append(('loop_narrow_self_reassign', edit(source, selects + [site])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
