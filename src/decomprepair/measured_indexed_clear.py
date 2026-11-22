"""Stage a measured global base and displacement in a masked clearing loop."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_indexed_clear'

_LOOP = re.compile(
    rf'\s*(?P<counter>{IDENT})\s*=\s*0\s*;\s*do\s*(?P<open>\{{)\s*'
    rf'\*\s*\(\s*s32\s*\*\s*\)\s*\(\s*\(\s*\(\s*(?P=counter)\s*&\s*0[xX][fF][fF]\s*\)\s*\*\s*4\s*\)\s*\+\s*'
    rf'\(\s*\(\s*\(\s*(?P<slot>{IDENT})\s*&\s*0[xX][fF][fF]\s*\)\s*\*\s*{NUMBER}\s*\)\s*\+\s*'
    rf'(?P<global>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\s*\)\s*\)\s*=\s*0\s*;\s*'
    rf'(?P=counter)\s*\+=\s*1\s*;\s*\}}\s*while\s*\(\s*\(\s*u32\s*\)\s*\(\s*(?P=counter)\s*&\s*0[xX][fF][fF]\s*\)\s*<\s*{NUMBER}\s*\)\s*;\s*')


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s32|u32)\s*;', header)
            or '__repair_clear_' in context):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    body = part.clean[part.opening + 1:end - 1]
    hit = _LOOP.search(body)
    if not hit or body[hit.end():].strip():
        return []
    counter, slot, global_ = (hit[k] for k in ('counter', 'slot', 'global'))
    if len({counter, slot, global_}) != 3:
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
    prefix = body[:hit.start()]
    if (decls.get(counter) != 's32' or re.sub(rf'\bs32\s+{re.escape(counter)}\s*;', '', prefix).strip()
            or not re.search(rf'\bs32\s+{re.escape(slot)}\s*\)', signature)
            or not re.search(rf'\bextern\s+s32\s+{re.escape(global_)}\s*;', part.clean[:part.opening])
            or re.search(rf'\b{re.escape(global_)}\b', header)
            or re.search(r'/[*/]|#', source[part.opening + 1 + hit.start():part.opening + 1 + hit.end()])):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (counter, slot, global_) for line in macros):
        return []
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    high = f'lui $v1, %hi({global_})'
    load = f'lw $v1, %lo({global_})($v1)'
    earlier = [i for i, (a, b) in enumerate(lines) if a == high and not b]
    later = [i for i, (a, b) in enumerate(lines) if b == high and not a]
    offset = integer(hit['offset'])
    if (len(earlier) != 1 or len(later) != 1 or later[0] <= earlier[0]
            or earlier[0] + 1 >= len(lines) or lines[earlier[0]+1] != (load, '')
            or later[0] + 1 >= len(lines) or lines[later[0]+1] != ('', load)
            or not any(a == f'addiu $v1, $v0, {offset}' for a, _ in lines)
            or not any(b == f'sw $zero, {offset}($v0)' for _, b in lines)):
        return []
    # The computed stores may alias the global. This is a target-led
    # snapshot hypothesis; the caller must still compile and judge it.
    start = part.opening + 1
    changes = [(start, start, '\n    s32 __repair_clear_global;\n    s32 __repair_clear_offset;'),
               (start + hit.start('counter'), start + hit.start('counter'), f'__repair_clear_global = {global_};\n    '),
               (start + hit.end('open'), start + hit.end('open'), f'\n        __repair_clear_offset = {hit["offset"]};'),
               (start + hit.start('global'), start + hit.end('global'), '__repair_clear_global'),
               (start + hit.start('offset'), start + hit.end('offset'), '__repair_clear_offset')]
    return [(FAMILY, edit(source, changes))]
