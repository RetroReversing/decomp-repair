"""Try widths indicated by target loads from inferred byte arrays."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view

_ACCESS = re.compile(
    rf'\*\(\s*(?P<table>{IDENT})\s*\+\s*\(\s*(?P<index>{IDENT})\s*\*\s*(?P<stride>{NUMBER})\s*\)\s*\)'
)
_LOAD = re.compile(rf'(?P<op>lb|lbu|lh|lhu|lw)\s+\$\w+,\s*%lo\((?P<symbol>{IDENT})\)\(\$\w+\)')


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    context = part.clean + '\n' + header
    widths = {}
    for marker, left, right in rows:
        if marker == ' ':
            continue
        a, b = _LOAD.fullmatch(left), _LOAD.fullmatch(right)
        if not a or not b or a['symbol'] != b['symbol'] or b['op'] not in ('lb', 'lbu'):
            continue
        if a['op'] in ('lhu', 'lw'):
            widths.setdefault(a['symbol'], set()).add('u16' if a['op'] == 'lhu' else 'u32')
    edits = []
    start = part.opening + 1
    for hit in _ACCESS.finditer(part.body):
        table = hit['table']
        choices = widths.get(table, set())
        after = part.body[hit.end():]
        before = part.body[:hit.start()].rstrip()
        if (re.match(r'\s*(?:=(?!=)|[+*/%&|^<>-]=|\+\+|--)', after)
                or before.endswith(('&', '++', '--'))
                or len(choices) != 1
                or not re.search(rf'\bextern\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', context)
                or re.search(rf'\bvolatile\b[^;]*\b{re.escape(table)}\b', context)):
            continue
        kind = next(iter(choices))
        replacement = f'*({kind} *)({table} + ({hit["index"]} * {hit["stride"]}))'
        edits.append((start + hit.start(), start + hit.end(), replacement))
    if not edits or len(edits) > 4:
        return []
    result = [('measured_inferred_table_widths', edit(source, edits))]
    if len(edits) > 1:
        result.extend(('measured_inferred_table_width', edit(source, [change])) for change in edits)
    return result
