"""Recover a staged call argument and a shared counter across two reset loops."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .mips import normalized_integer_lines

FAMILY = 'measured_reset_loops'

_PATTERN = re.compile(
    rf'(?P<save>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\)\s*;\s*'
    rf'(?P<first>{IDENT})\s*=\s*0\s*;\s*(?P<p>{IDENT})\s*=\s*(?P=base)\s*;\s*do\s*\{{\s*'
    rf'M2C_FIELD\(\s*(?P=p)\s*,\s*s16\s*\*\s*,\s*(?P<firstoff>{NUMBER})\s*\)\s*=\s*0\s*;\s*'
    rf'(?P=first)\s*\+=\s*1\s*;\s*(?P=p)\s*\+=\s*2\s*;\s*\}}\s*while\s*\(\s*(?P=first)\s*<\s*(?P<count1>{NUMBER})\s*\)\s*;\s*'
    rf'(?P<second>{IDENT})\s*=\s*0\s*;\s*(?P<cursorinit>(?P<q>{IDENT})\s*=\s*(?P=base)\s*;)\s*do\s*\{{\s*'
    rf'(?P<byte>M2C_FIELD\(\s*(?P=q)\s*,\s*s8\s*\*\s*,\s*(?P<secondoff>{NUMBER})\s*\)\s*=\s*0\s*;)\s*'
    rf'(?P=second)\s*\+=\s*1\s*;\s*(?P<cursorend>(?P=q)\s*=\s*(?P=base)\s*\+\s*(?P=second)\s*;)\s*'
    rf'\}}\s*while\s*\(\s*(?P=second)\s*<\s*(?P<count2>{NUMBER})\s*\)\s*;\s*'
    rf'(?P<call>{IDENT})\s*\(\s*(?P<load>M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P<loadoff>{NUMBER})\s*\))\s*,', re.S)


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s8|s16|s32|u32)\s*;', header)
            or '__repair_reset_head' in context):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])):
        return []
    matches = list(_PATTERN.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return []
    hit = matches[0]
    names = [hit[k] for k in ('save', 'base', 'first', 'p', 'second', 'q')]
    if len(set(names)) != len(names) or re.search(r'/[*/]|#', source[hit.start():hit.end()]):
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    if (decls.get(hit['save']) != 's32' or decls.get(hit['first']) != 'u32'
            or decls.get(hit['second']) != 'u32'
            or any(len(re.findall(rf'\bvoid\s*\*\s*{re.escape(hit[k])}\b', part.clean)) != 1
                   for k in ('base', 'p', 'q'))):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in names + [hit['call']] for line in macros):
        return []
    if any(re.search(rf'\b{re.escape(hit[k])}\b', part.clean[hit.end('cursorend'):part.end])
           for k in ('first', 'q')):
        return []
    # The second counter's last use is its loop condition, and its first is
    # the initializer. The first counter is dead there and can be reused.
    loopend = part.clean.find(';', hit.end('count2')) + 1
    if (not loopend or re.search(rf'\b{re.escape(hit["second"])}\b', part.clean[loopend:part.end])
            or any(re.search(rf'&\s*{re.escape(hit[k])}\b', part.body) for k in ('save', 'base', 'first', 'p', 'second', 'q'))):
        return []
    n1, n2, off1, off2, load = (integer(hit[k]) for k in ('count1', 'count2', 'firstoff', 'secondoff', 'loadoff'))
    if not (1 <= n1 <= 16 and 1 <= n2 <= 16):
        return []
    read = set(range(load, load + 4))
    written = set(range(off1, off1 + 2 * n1)) | set(range(off2, off2 + n2))
    if read & written:
        return []
    diff = [normalized_integer_lines((a, b)) for _, a, b in rows]
    wanted = re.compile(rf'lw \$a0, {load}\(\$s[0-7]\)')
    early = [(i, a) for i, (a, b) in enumerate(diff) if a and not b and wanted.fullmatch(a)]
    if len(early) != 1 or not any(i > early[0][0] and not a and b == early[0][1]
                                  for i, (a, b) in enumerate(diff)):
        return []
    prefix = part.clean[part.opening+1:hit.start()].rstrip()
    if prefix and prefix[-1] not in ';{}':
        return []
    second_start = hit.start('second')
    section = source[second_start:loopend]
    for start, end, replacement in sorted([
            (hit.start('cursorinit') - second_start, hit.end('cursorinit') - second_start, ''),
            (hit.start('cursorend') - second_start, hit.end('cursorend') - second_start, ''),
            (hit.start('byte') - second_start, hit.start('byte') - second_start,
             f'{hit["q"]} = {hit["base"]} + {hit["second"]};\n        '),
    ], reverse=True):
        section = section[:start] + replacement + section[end:]
    section = re.sub(rf'\b{re.escape(hit["second"])}\b', hit['first'], section)
    load_text = source[slice(*hit.span('load'))]
    changes = [(part.opening + 1, part.opening + 1, '\n    s32 __repair_reset_head;'),
               (hit.start(), hit.start(), f'__repair_reset_head = {load_text};\n    '),
               (second_start, loopend, section), (*hit.span('load'), '__repair_reset_head')]
    return [(FAMILY, edit(source, changes))]
