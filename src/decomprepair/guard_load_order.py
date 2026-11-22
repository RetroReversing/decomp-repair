"""Use measured load order to schedule independent reads in a comma guard."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close
from .pointer_pair_repairs import qualified_types

FAMILY = 'guard_load_order'

_CHAIN = re.compile(rf'''
    (?P<x>(?P<array>{IDENT})\[0\]\s*=\s*
      \*\(\(f32\s*\*\)\s*\(\(\(char\s*\*\)\s*
      (?P<helper>{IDENT})\((?P<slot>{IDENT})\)\)\s*\+\s*(?P<xoff>{NUMBER})\)\)),
    \s*(?P<field>(?P<result>{IDENT})\s*=\s*
      \(\(\*\(\(s8\s*\*\)\s*\(\(\(char\s*\*\)\s*
      \(\*\(\(void\s*\*\*\)\s*\(\(\(char\s*\*\)\s*(?P<base>{IDENT})\)
      \s*\+\s*(?P<ptr_off>{NUMBER})\)\)\)\)\s*\+\s*(?P<byte_off>{NUMBER})\)\)\)
      \s*\*\s*{NUMBER}\)\s*\+\s*\(\(char\s*\*\)\s*\(&(?P<table>{IDENT})\)\)),
    \s*(?P<z>(?P=array)\[2\]\s*=\s*0),
    \s*(?P<y>(?P=array)\[1\]\s*=\s*
      \*\(\(f32\s*\*\)\s*\(\(\(char\s*\*\)\s*\(\*(?P=slot)\)\)
      \s*\+\s*(?P<yoff>{NUMBER})\)\))(?=\s*,)
''', re.X)


def _indices(instructions, op, offset):
    return [i for i, text in enumerate(instructions)
            if (match := re.fullmatch(rf'{op} \$\w+, (0x[0-9a-f]+|[0-9]+)\(\$\w+\)', text))
            and int(match[1], 0) == offset]


def _witness(rows, hit):
    offsets = [integer(hit[k]) for k in ('ptr_off', 'xoff', 'byte_off')]
    ptr, x, byte = offsets
    for i in _indices([row[1] for row in rows], 'lw', ptr):
        target = [row[1] for row in rows[i:i+6]]
        candidate = [row[2] for row in rows[max(0, i-4):i+6]]
        x_load = _indices(target, 'lwc1', x)
        byte_load = _indices(target, 'lb', byte)
        old_x = _indices(candidate, 'lwc1', x)
        old_ptr = _indices(candidate, 'lw', ptr)
        if x_load and byte_load and old_x and old_ptr and old_x[0] < old_ptr[0]:
            return True
    return False


def variants(source, name, rows, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__)\b', part.body):
        return []
    context = _blank(header) + '\n' + part.clean
    if {'s8', 'f32'} & qualified_types(context):
        return []
    macro_text = context.replace('\\\n', ' ')
    macros = re.findall(r'(?m)^[ \t]*#\s*(?:define|undef)\s+([^\n]+)', macro_text)
    guards = []
    for match in re.finditer(r'\bif\s*\(', part.body):
        opening = part.opening + match.end()
        end = close(part.clean, opening)
        if end:
            guards.append((opening, end))
    out = []
    for hit in _CHAIN.finditer(part.clean, part.opening + 1, part.end):
        array, helper, slot, result, base, table = (hit[k] for k in ('array', 'helper', 'slot', 'result', 'base', 'table'))
        enclosing = next((start for start, end in guards if start < hit.start() < hit.end() < end), None)
        if enclosing is None:
            continue
        groups = []
        for item in re.finditer(r'[()]', part.clean[enclosing:hit.start()]):
            if item[0] == '(':
                groups.append(enclosing + item.start())
            else:
                groups.pop()
        if not groups or not part.clean[enclosing:groups[-1]].rstrip().endswith(('(', '&&', '||')):
            continue
        names = {array, helper, slot, result, base, table}
        if len(names) != 6 or any((names | {'s8', 'f32'}) & set(re.findall(IDENT, macro)) for macro in macros):
            continue
        if not re.search(rf'\bvoid\s*\*\s*{helper}\s*\(\s*void\s*\*\*\s*({IDENT})\s*\)\s*\{{\s*return\s+\*\1\s*;\s*\}}',
                         part.clean[:part.opening]):
            continue
        prefix = part.clean[part.opening + 1:hit.start()]
        if len(re.findall(rf'\b{array}\b', prefix)) != 1 or not re.search(rf'\bf32\s+{array}\s*\[\s*3\s*\]\s*;', prefix):
            continue
        if not re.search(rf'\bvoid\s*\*\*\s*{slot}\s*;', prefix):
            continue
        if (not re.search(rf'\bvoid\s*\*\s*{result}\s*;', prefix)
                or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{result}\b', part.body)):
            continue
        signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
        if not re.search(rf'\bvoid\s*\*\s*{base}\s*(?:,|\))', signature):
            continue
        if source[hit.start():hit.end()] != hit[0] or not _witness(rows, hit):
            continue
        replacement = ', '.join(hit[k] for k in ('field', 'x', 'y', 'z'))
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), replacement)])))
    return out[:2]
