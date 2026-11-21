"""Normalize a staged 3-by-3 float grid when the target schedules its stores differently."""

import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'measured_float_grid_stores'
FLOAT = r'(?:f32|float)'
FLOAT_LITERAL = r'(?:[0-9]+\.[0-9]*|\.[0-9]+)[fF]'
TERM = rf'(?:{FLOAT_LITERAL}|{IDENT})'
PURE = rf'{TERM}(?:\s*[+*\-]\s*{TERM})?'
STORE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<base>{IDENT})\s*\[\s*(?P<row>[0-2])\s*\]'
    rf'\s*\[\s*(?P<col>[0-2])\s*\]\s*=\s*(?P<expr>{PURE})\s*;[ \t]*$'
)
DECL = re.compile(
    rf'(?m)^[ \t]*(?:register[ \t]+)?{FLOAT}[ \t]+(?P<name>{IDENT})\s*=\s*(?P<rhs>[^;\n]+);[ \t]*\n'
)
PRODUCT = re.compile(rf'(?P<first>{IDENT})\s*\*\s*(?P<second>{IDENT})')
PADDING = re.compile(rf'(?m)^[ \t]*volatile (?:f64|double) (?P<name>{IDENT})\[1\];[ \t]*\n')
FP_STORE = re.compile(r'swc1 \$f\d+, (?:0x[0-9a-f]+|\d+)?\((\$\w+)\)')


def _mismatched_float_stores(rows):
    for marker, target, candidate in rows:
        if marker == ' ':
            continue
        a, b = FP_STORE.fullmatch(target), FP_STORE.fullmatch(candidate)
        if a and b and a[1] == b[1] and target.split(', ')[1] != candidate.split(', ')[1]:
            return True
    return False


def _grid(part, name):
    stores = list(STORE.finditer(part.clean, part.opening + 1, part.end))
    if (len(stores) != 9 or len({(m['row'], m['col']) for m in stores}) != 9
            or len({m['base'] for m in stores}) != 1):
        return []
    base = stores[0]['base']
    start, _ = find(part.source, name)
    signature = part.clean[start:part.opening]
    if not re.search(rf'(?:[(,]\s*){FLOAT}\s+{base}\s*\[\s*3\s*\]\s*\[\s*3\s*\]\s*\)', signature):
        return []
    if any(part.clean[a.end():b.start()].strip() for a, b in zip(stores, stores[1:])):
        return []
    if not re.fullmatch(r'\s*}\s*', part.clean[stores[-1].end():part.end]):
        return []
    return stores


def _normalize(source, part, stores):
    first = stores[0].start()
    prefix = part.clean[part.opening + 1:first]
    if DECL.sub('', PADDING.sub('', prefix)).strip():
        return None
    declarations = list(DECL.finditer(part.clean, part.opening + 1, first))
    decls = {m['name']: m for m in declarations}
    if len(declarations) != len(decls) or any(
        not re.fullmatch(rf'(?:{PURE}|{IDENT}\s*->\s*{IDENT})', m['rhs']) for m in declarations
    ):
        return None
    inline = {}
    for name, declaration in decls.items():
        rhs = declaration['rhs']
        if not re.fullmatch(PURE, rhs) or name in re.findall(IDENT, rhs):
            continue
        inputs = re.findall(IDENT, re.sub(FLOAT_LITERAL, '', rhs))
        if any(i not in decls or decls[i].end() > declaration.start() for i in inputs):
            continue
        # The prefix has no assignments to these inputs and no calls.
        if len(re.findall(rf'\b{name}\b', part.body)) != 2:
            continue
        if any(re.search(rf'\b{name}\b', m['expr']) for m in stores):
            inline[name] = declaration
    if len(inline) < 4:
        return None
    result = []
    for m in sorted(stores, key=lambda x: (x['row'], x['col'])):
        rhs = re.sub(TERM, lambda hit: '(' + inline[hit[0]]['rhs'] + ')' if hit[0] in inline else hit[0], m['expr'])
        if any(token not in decls for token in re.findall(IDENT, re.sub(FLOAT_LITERAL, '', rhs))):
            return None
        result.append(f'{m["indent"]}{m["base"]}[{m["row"]}][{m["col"]}] = {rhs};')
    edits = [(m.start(), m.end(), '') for m in inline.values()]
    for pad in PADDING.finditer(part.clean, part.opening + 1, first):
        if len(re.findall(rf'\b{pad["name"]}\b', part.body)) == 1:
            edits.append((pad.start(), pad.end(), ''))
    edits.append((first, stores[-1].end(), '\n'.join(result)))
    return edit(source, edits)


def variants(source, name, rows):
    """Try row-major stores and repartition single-use float expression lifetimes."""
    if '[' not in source or not _mismatched_float_stores(rows):
        return []
    part = view(source, name)
    stores = _grid(part, name) if part else []
    if not stores or (normal := _normalize(source, part, stores)) is None:
        return []
    result = [(FAMILY, normal)]
    new = view(normal, name)
    declarations = {m['name']: m for m in DECL.finditer(new.clean, new.opening + 1, new.end)}
    for decl in declarations.values():
        product = PRODUCT.fullmatch(decl['rhs'])
        if not product:
            continue
        left, right = product['first'], product['second']
        if left != right and left in declarations and right in declarations:
            result.append((FAMILY, edit(normal, [(*decl.span('rhs'), f'{right} * {left}')])))
    return result[:16]
