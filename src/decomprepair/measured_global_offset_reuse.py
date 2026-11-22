"""Fold an equivalent global address temporary into its generated field accesses."""

import re

from . import frame_padding_repairs
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines

FAMILIES = ('measured_global_offset_reuse', 'global_offset_with_frame')


def variants(source, name, header, rows, asm):
    part = view(source, name)
    context = source + '\n' + header
    if not part or re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp)\b', part.clean):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])):
        return []
    pattern = re.compile(rf'\b(?P<local>{IDENT})\s*=\s*\(\s*(?:char|s8)\s*\*\s*\)\s*&\s*'
                         rf'(?P<global>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\s*;')
    hits = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return []
    hit = hits[0]
    local, global_ = hit['local'], hit['global']
    prefix = part.clean[part.opening + 1:hit.start()].rstrip()
    if (local == global_ or (prefix and prefix[-1] not in ';{}') or prefix.count('{') != prefix.count('}')
            or re.search(r'\bgoto\b', prefix) or re.search(r'/[*/]|#', source[hit.start():hit.end()])
            or len(re.findall(rf'\bvoid\s*\*\s*{re.escape(local)}\s*;', part.body)) != 1
            or re.search(rf'\b(?:static|extern|const)\s+void\s*\*\s*{re.escape(local)}\b', part.body)
            or not re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(global_)}\s*;', part.clean[:part.opening])
            or re.search(rf'\b{IDENT}\s+\**\s*{re.escape(global_)}\s*(?=[;=,\[])', part.body)):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (local, global_) for line in macros):
        return []
    field = re.compile(rf'M2C_FIELD\(\s*{re.escape(local)}\s*,\s*(?P<type>{IDENT}\s*\*+)\s*,\s*'
                       rf'(?P<offset>{NUMBER})\s*\)')
    uses = list(field.finditer(part.clean, hit.end(), part.end))
    if not 2 <= len(uses) <= 8 or len(re.findall(rf'\b{re.escape(local)}\b', part.body)) != len(uses) + 2:
        return []
    base = integer(hit['offset'])
    offsets = [integer(use['offset']) for use in uses]
    if any(base + offset > 0x7FFFFFFF for offset in offsets):
        return []
    # The target forms the same relocated address in a scratch register and
    # only retains it after the null test; the draft dedicates a saved register.
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    matched = False
    for i in range(len(lines) - 2):
        left = re.fullmatch(r'lui (\$v0), %hi\(([^)]+)\)', lines[i][0])
        right = re.fullmatch(r'lui (\$s[0-7]), %hi\(([^)]+)\)', lines[i][1])
        if not left or not right or left[2] != right[2]:
            continue
        symbol = re.escape(left[2])
        if (re.fullmatch(rf'addiu \$v0, \$v0, %lo\({symbol}\)', lines[i+1][0])
                and re.fullmatch(rf'addiu {re.escape(right[1])}, {re.escape(right[1])}, %lo\({symbol}\)', lines[i+1][1])
                and lines[i+2] == ('lw $s0, ($v0)', f'lw $s0, ({right[1]})')
                and any(a == 'move $s2, $v0' and b == f'move $s3, {right[1]}' for a, b in lines[i+3:])):
            matched = True
            break
    if not matched:
        return []
    changes = [(hit.start(), hit.end(), '')]
    for use, offset in zip(uses, offsets):
        if re.search(r'/[*/]|#', source[use.start():use.end()]):
            return []
        typ = source[slice(*use.span('type'))]
        changes.append((use.start(), use.end(), f'M2C_FIELD(&{global_}, {typ}, 0x{base + offset:X})'))
    moved = edit(source, changes)
    result = [(FAMILIES[0], moved)]
    if not re.search(r'\bscratch(?:_word)?\b', header):
        result.extend((FAMILIES[1], candidate) for _, candidate in frame_padding_repairs.variants(moved, name, asm))
    return result
