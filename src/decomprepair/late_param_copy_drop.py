"""A parameter copied into a local only after the local was already read: the reads use the parameter.

A search that slides statements can leave `arg0 = arg0_in;` below the statements that read `arg0`:

    void f(void *arg0_in) {                     void f(void *arg0_in) {
        void *arg0;                                 *(s32 *)((char *)arg0_in + 0x34) += 1;
        *(s32 *)((char *)arg0 + 0x34) += 1;  ->     ...
        arg0 = arg0_in;
        ...

That reads an uninitialised local, which no game did, and the judge can score it well because the allocator gives the
two pseudos one register. `parameter_copy_drop` declines it (the local is read before its copy). Dropping the copy is
the faithful program, but on its own it can score far worse (105 -> 790 on an 81-instruction N64 object update built
by SN's GCC): the order of the statements around the copy has to change with it (790 -> 20 with `staged_store_first`),
so each such step is offered together with the drop as one child.

Offered when the local is declared with the parameter's type, only the copy writes it, nothing takes its address, the
parameter is not mentioned anywhere else and the local is read before the copy.
"""
import re

from . import staged_store_first
from .integer_repair_support import IDENT, _address_taken, edit, view
from .parameter_copy_drop_repairs import TYPE, _norm, _parameters

FAMILY = 'late_param_copy_drop'
FAMILIES = (FAMILY,)
LIMIT = 8


def _name(word):
    return rf'(?<![\w.])(?<!->){word}\b'


def _drop(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return None
    body, base = part.body, part.opening + 1
    parameters = _parameters(part)
    for copy in re.finditer(rf'(?:(?<=[;{{}}])|^)[ \t]*({IDENT})[ \t]*=[ \t]*({IDENT})[ \t]*;', body, re.M):
        local, param = copy[1], copy[2]
        if param not in parameters or local in parameters or local == param:
            continue
        if body[:copy.start()].count('{') != body[:copy.start()].count('}'):
            continue
        rest = body[:copy.start()] + body[copy.end():]
        if re.search(_name(param), rest) or _address_taken(rest, local):
            continue
        declaration = re.search(rf'(?m)^[ \t]*(?:register\s+)?({TYPE})((?:\s*\*)*)\s*\b{local}\s*;[ \t]*\n', body[:copy.start()])
        if not declaration:
            continue
        kind = _norm(declaration[1]) + ' ' * bool(declaration[2].strip()) + declaration[2].replace(' ', '').strip()
        if kind != parameters[param]:
            continue
        uses = [m for m in re.finditer(_name(local), body)
                if not declaration.start() <= m.start() < declaration.end() and not copy.start() <= m.start() < copy.end()]
        if not any(m.start() < copy.start() for m in uses):
            continue
        if any(re.match(r'\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)', body[m.end():])
               or body[:m.start()].rstrip().endswith(('++', '--')) for m in uses):
            continue
        line_start = body.rfind('\n', 0, copy.start()) + 1
        line_end = body.find('\n', copy.end()) + 1
        whole = not body[line_start:copy.start()].strip() and line_end and not body[copy.end():line_end].strip()
        edits = [(base + (line_start if whole else copy.start()), base + (line_end if whole else copy.end()), ''),
                 (base + declaration.start(), base + declaration.end(), '')]
        edits += [(base + m.start(), base + m.end(), param) for m in uses]
        return edit(source, edits)
    return None


def variants(source, name, header=''):
    dropped = _drop(source, name)
    if not dropped:
        return []
    out = [(FAMILY, dropped)]
    out += [(FAMILY, child) for _, child in staged_store_first.variants(dropped, name, header)]
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
