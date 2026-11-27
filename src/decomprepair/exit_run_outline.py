"""A run that ends the function early, written after the function's end behind a label.

GCC lays an `if (x == 0) { ...; return; }` out where it stands, right before the code the other paths reach. A target
that has that run last (after the function's final statements, reached by a branch forward and ending in the shared
epilogue) was written with it out of line:

    if (n < 0x12D) {                          if (n < 0x12D) {
        p = get(o);                               p = get(o);
        if (p == NULL) { drift(o); return; }      if (p == NULL) { goto repair_exit; }
        work(p);                                  work(p);
    }                                         }
    o->state = 2;                             o->state = 2;
                                              return;
                                          repair_exit:
                                              drift(o);
                                              return;

m2c writes the same run after the `if` that jumps past it (`if (p) { ...; goto done; } drift; return;`), so both forms
are offered: the whole body of an `if` that ends in `return`, and the statements after the last compound statement of a
block that ends in `return`. On a 117-instruction N64 function (SN GCC 2.8.1) this took the saved best from 400 to 10
(1155 to 115 from a structured rewrite).

The run holds no label, `case`, `break` or `continue`, names no local declared in a block around it, and other code
follows its blocks before the function ends. The meaning is unchanged. A candidate; the exact judge decides.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, view

FAMILY = 'exit_run_outline'
FAMILIES = (FAMILY,)
LIMIT = 6
_RETURN = re.compile(r'return\b[^;{}]*;\Z')
_LABEL = re.compile(r'(?:\A|[;{}])\s*[A-Za-z_]\w*\s*:(?!:)')
_WORD = re.compile(r'\b(?:case|default|break|continue)\b')
_DECLARATION = re.compile(rf'(?:\A|[;{{}}])\s*(?:(?:const|volatile|static|register|unsigned|signed|struct|union)\s+)*'
                          rf'(?!return\b|goto\b|else\b){IDENT}(?:\s+|\s*\*+\s*)(?P<name>{IDENT})\s*(?=[=;\[,])')


def _runs(clean, opening, closing):
    """(start, end) of the runs to move out of the block clean[opening:closing]: all of an `if` body, and what follows
    the block's last compound statement. Both end in the block's final `return`."""
    spans = statements(clean, opening + 1, closing)
    if not spans or not _RETURN.fullmatch(clean[spans[-1][0]:spans[-1][1]]):
        return
    before = clean[:opening].rstrip()
    if len(spans) > 1 and before.endswith(')'):
        yield spans[0][0], spans[-1][1]
    for index in range(len(spans) - 2, 0, -1):
        if clean[spans[index - 1][1] - 1] == '}' and re.match(r'if\b', clean[spans[index - 1][0]:]):
            yield spans[index][0], spans[-1][1]
            return


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, opening = part.clean, part.opening
    pairs = brace_pairs(clean, opening, part.end)
    if not pairs or opening not in pairs:
        return []
    end = pairs[opening]
    blocks = sorted((a, b) for a, b in pairs.items() if a != opening)
    void = re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', clean[:opening]) is not None
    top = statements(clean, opening + 1, end)
    if not top:
        return []
    returns = clean[top[-1][0]:top[-1][1]].startswith('return')
    if not returns and not void:
        return []
    label, number = 'repair_exit', 1
    while re.search(rf'\b{label}\b', clean):
        number += 1
        label = f'repair_exit{number}'
    found = []
    for start, close in blocks:
        for first, last in _runs(clean, start, close):
            run = clean[first:last]
            if _WORD.search(run) or _LABEL.search(run) or clean[first:last].count(';') < 2:
                continue
            around = [(a, b) for a, b in blocks if a < first and b >= last]
            outermost = min(around)[1]
            if not re.sub(r'[\s{};]|\breturn\b', '', clean[outermost + 1:end]):
                continue
            hidden = set()
            for a, _ in around:
                hidden.update(m['name'] for m in _DECLARATION.finditer(clean[a:first]))
            if hidden & set(re.findall(IDENT, run)):
                continue
            if _DECLARATION.search(';' + run):
                continue
            tail = ('' if returns else '    return;\n') + f'{label}:\n    {source[first:last].strip()}\n'
            body = source[:first] + f'goto {label};' + source[last:end]
            child = body.rstrip() + '\n' + tail + source[end:]
            found.append((FAMILY, child))
            if len(found) == LIMIT:
                return found
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
