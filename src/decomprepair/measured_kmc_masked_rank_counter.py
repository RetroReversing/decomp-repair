"""Try byte storage for a bounded rank counter returned modulo 256."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines

_RETURN = re.compile(rf'\breturn\s*\(\s*(?P<count>{IDENT})\s*-\s*1\s*\)\s*&\s*0[xX][fF][fF]\s*;')
_LOOP = re.compile(rf'\bwhile\s*\(\s*\(\s*u32\s*\)\s*\(\s*(?P<index>{IDENT})\s*&\s*0[xX][fF][fF]\s*\)\s*<\s*4[uU]?\s*\)')


def variants(source, name, header, rows):
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not any(left.startswith('bnel $v0, $zero, ') and right == 'subu $a2, $a2, $v0'
               for left, right in changed):
        return []
    if ('addiu $a2, $a2, -1', '') not in changed:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean):
        return []
    returned = list(_RETURN.finditer(part.body))
    loops = list(_LOOP.finditer(part.body))
    if len(returned) != 1 or len(loops) != 1:
        return []
    count, index = returned[0]['count'], loops[0]['index']
    if count == index or re.search(rf'\b{re.escape(count)}\b', header + '\n' + part.clean[:part.opening]):
        return []
    counter = re.escape(count)
    decls = list(re.finditer(rf'\bs32\s+{counter}\s*;', part.body))
    if (len(decls) != 1 or len(re.findall(rf'\b{counter}\b', part.body)) != 4
            or len(re.findall(rf'\b{counter}\s*=\s*4\s*;', part.body)) != 1
            or len(re.findall(rf'\b{counter}\s*-=\s*1\s*;', part.body)) != 1):
        return []
    idx = re.escape(index)
    if (re.search(rf'(?:&|\+\+|--)\s*{idx}\b', part.body)
            or re.search(rf'(?m)^\s*#\s*define\s+{idx}\b', part.clean + '\n' + header)
            or len(re.findall(rf'\b{idx}\s*=\s*0\s*;', part.body)) != 1
            or len(re.findall(rf'\b{idx}\s*\+=\s*1\s*;', part.body)) != 1
            or re.search(rf'\b{idx}\s*(?:=(?!=)|\+=|-=|\+\+|--)',
                         re.sub(rf'\b{idx}\s*(?:=\s*0|\+=\s*1)\s*;', '', part.body))):
        return []
    start = part.opening + 1 + decls[0].start()
    return [('measured_masked_rank_counter', edit(source, [(start, start + 3, 'u8')]))]
