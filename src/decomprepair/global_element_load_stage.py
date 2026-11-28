"""A global's element stored last, read into a local above the statement before it.

A draft writes each store with its value in place:

    p->velX = -p->velX;                      u8 tag;  ...  p->velX = -p->velX;
    p->velY = -p->velY;           ->         tag = gTags[3];
    p->state = gTags[3];                     p->velY = -p->velY;
    call(p);                                 p->state = tag;

The first scheduler keeps a load behind the stores that precede it in the source, so the two negations' loads and
stores run into each other and take different registers. The target read the global between them. `copy_load_hoist`
only reads typed `M2C_FIELD` or record-cast cells, and `temporary_hoist` stops at the first statement that writes
memory, so neither offered it. Measured on a 204-instruction N64 collision handler (SN GCC 2.8.1 `-G0 -mips3 -O2`):
595 -> 0 with this one edit. Moving the whole store up instead scored 2550.

For each statement `STORE = G[k];` (or `STORE = G;`) directly in a block, `G` declared `extern` with a scalar type and
`STORE` a member or dereference, the read is held in a new local assigned above one of the plain statements before it
(no call, no write of `G`), nearest first. That those stores do not overlap `G` is the assumption the target's order
makes; the exact judge decides. A function with a `volatile` or inline assembly is left alone.
"""
import re

from .copy_load_hoist import _after_declarations, _blocks, _fresh, _line_indent, _Plain, _statements
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_element_load_stage'
FAMILIES = (FAMILY,)
POSITIONS = 4
LIMIT = 16
_SCALAR = r'(?:[su](?:8|16|32)|f32|f64)'
_COPY = re.compile(rf'(?P<lhs>[^=;{{}}]+?)\s*(?<![-+*/%&|^<>!=])=(?!=)\s*'
                   rf'(?P<load>(?P<name>{IDENT})(?:\s*\[\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\])?)\s*;')


def _element_type(context, name, indexed):
    """The scalar type of `extern T name[...]` (indexed) or `extern T name;`, else None."""
    tail = r'\s*\[[^\]]*\]\s*;' if indexed else r'\s*;'
    found = re.search(rf'\bextern\s+({_SCALAR})\s+{name}{tail}', context)
    return found.group(1) if found else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    clean = part.clean
    temp = _fresh(clean)
    if temp is None:
        return []
    context = _blank(header or '') + '\n' + clean
    at = _after_declarations(clean, part)
    result = []
    for low, high in _blocks(clean, part.opening + 1, part.end - 1):
        spans = _statements(clean, low, high)
        plains = [_Plain(clean[a:b]) for a, b in spans]
        for index in range(len(spans) - 1, 0, -1):
            a, b = spans[index]
            found = _COPY.fullmatch(clean[a:b])
            if not found or not re.search(r'->|\*|\.', found['lhs']):
                continue
            kind = _element_type(context, found['name'], '[' in found['load'])
            if kind is None:
                continue
            written = re.compile(rf'\b{found["name"]}\b')
            offered = 0
            for before in range(index - 1, -1, -1):
                plain = plains[before]
                if not plain.ok or any(written.search(lhs) for lhs in plain.stores):
                    break
                start = spans[before][0]
                line = source.rfind('\n', 0, start) + 1
                if source[line:start].strip():
                    break
                indent = _line_indent(source, start)
                result.append((FAMILY, edit(source, [
                    (at, at, f'    {kind} {temp};\n'),
                    (line, line, f'{indent}{temp} = {found["load"]};\n'),
                    (a + found.start('load'), a + found.end('load'), temp)])))
                offered += 1
                if offered >= POSITIONS or len(result) >= LIMIT:
                    break
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
