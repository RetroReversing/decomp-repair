"""Narrow a masked index when KMC's target keeps it in the byte argument register."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 40:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('', 'move $a1, $a0') not in changes
            or ('andi $a0, $a0, 7', 'andi $a0, $a1, 7') not in changes
            or 'andi $v0, $a1, 255' not in target):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    signature = re.search(rf'\bs32 {re.escape(name)}\(u8 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not signature or re.search(r'\bvolatile\b', part.body):
        return []
    body = part.body
    arg = signature[1]
    init = re.search(rf'\b(?P<local>{IDENT})\s*=\s*{re.escape(arg)}\s*&\s*7\s*;', body)
    if not init:
        return []
    local = init['local']
    declaration = re.search(rf'\b(?P<type>s32)\s+{re.escape(local)}\s*;', body[:init.start()])
    if (not declaration or len(re.findall(rf'\b{re.escape(local)}\b', body)) != 4
            or re.search(rf'(?:&|\+\+|--)\s*{re.escape(local)}\b', body)
            or re.search(rf'\b{re.escape(local)}\s*(?:[+*/&|^-]?=|\+\+|--)', body[init.end():])
            or len(re.findall(rf'\b{re.escape(local)}\s*&\s*0xFF\b', body[init.end():])) != 2):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + declaration.start('type'), start + declaration.end('type'), 'u8')])
    result = [('measured_masked_byte_index', fixed)]
    # An extra copy of the masked byte can also force the index into a
    # different register on each table arm. Reuse the immutable byte directly.
    assignment = re.search(rf'\b(?P<copy>{IDENT})\s*=\s*{re.escape(local)}\s*&\s*0[xX][fF][fF]\s*;', body[init.end():])
    if not assignment:
        return result
    copy = assignment['copy']
    decls = list(re.finditer(rf'\bs32\s+{re.escape(copy)}\s*;', body[:init.start()]))
    if len(decls) != 1 or copy == local:
        return result
    assignment_start = init.end() + assignment.start()
    assignment_end = init.end() + assignment.end()
    uses = list(re.finditer(rf'\b{re.escape(copy)}\b', body))
    if (len(uses) < 3 or any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(symbol)}\b', source + '\n' + header)
                               for symbol in (copy, local))
            or re.search(rf'(?:&|\+\+|--|\.|->)\s*{re.escape(copy)}\b', body)
            or re.search(rf'\b{re.escape(copy)}\s*(?:[+*/&|^-]?=|\+\+|--)', body[assignment_end:])):
        return result
    if any(hit.start() > decls[0].end() and hit.start() < assignment_start for hit in uses):
        return result
    remaining = [hit for hit in uses if hit.start() >= assignment_end]
    if not remaining:
        return result
    spans = [(start + declaration.start('type'), start + declaration.end('type'), 'u8'),
             (start + decls[0].start(), start + decls[0].end(), ''),
             (start + assignment_start, start + assignment_end, '')]
    spans.extend((start + hit.start(), start + hit.end(), f'({local} & 0xFF)') for hit in remaining)
    result.append(('measured_masked_byte_index_reuse', edit(source, spans)))
    return result
