"""Stage a pointer to a fixed-width array row before a simple guard.

In one KMC O1 loop, naming the real row used by the guard changed its
allocation and reduced the linked diagnostic from 936 to 881. The original
signed index is preserved; later reads may use a different index.
"""
import re

from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'array_row_guard_pointer'
LOCAL = '__repair_guard_row'
LIMIT = 6


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean, body = part.clean, part.body
    if re.search(rf'\b{LOCAL}\b', context) or re.search(r'\b(?:volatile|_Atomic|typedef)\b|\bgoto\s*\*', body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    declarations = re.compile(rf'(?m)^[ \t]*(?P<type>{IDENT})\s*\(\s*\*\s*(?P<row>{IDENT})\s*\)\s*\[\s*(?P<width>[1-9][0-9]*)\s*\]\s*;')
    result = []
    for decl in declarations.finditer(body):
        element, row = decl['type'], decl['row']
        pos = part.opening + 1 + decl.start('row')
        type_shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(element)}\s*(?=[;=,\[])'
        if (any(part.opening < a < pos < b for a, b in pairs.items())
                or {element, row, LOCAL} & macros or re.search(type_shadow, body)):
            continue
        shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(row)}\s*(?=[;=,\[])'
        typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(row)}\s*(?=[;=,\[])'
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*{re.escape(row)}\s*(?:[;=,\[])'
        if (len(re.findall(rf'\b{re.escape(row)}\s*\)\s*\[', body)) != 1
                or re.search(shadow, body) or re.search(typeof_shadow, body) or re.search(multi, body)):
            continue
        pattern = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<guard>if\s*\(\s*(?P<access>{re.escape(row)}\s*\[\s*(?P<index>{IDENT})\s*\]\s*\[\s*{IDENT}\s*\])\s*(?:==|!=)\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\))')
        for hit in pattern.finditer(body):
            if hit['index'] in macros or body[:hit.start('guard')].rstrip()[-1:] not in ('', ';', '{', '}'):
                continue
            at = part.opening + 1
            start = at + hit.start('guard')
            access_start, access_end = at + hit.start('access'), at + hit.end('access')
            # Replacing only the row subscript leaves the column and comparison untouched.
            row_access = re.match(rf'{re.escape(row)}\s*\[\s*{re.escape(hit["index"])}\s*\]', clean[access_start:access_end])
            if not row_access:
                continue
            insertion = f'{LOCAL} = {row}[{hit["index"]}];\n{hit["indent"]}'
            result.append((FAMILY, edit(source, [(at, at, f'\n    {element} *{LOCAL};'),
                                                (start, start, insertion),
                                                (access_start, access_start + row_access.end(), LOCAL)])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
