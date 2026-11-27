"""A sum of two loads stored last in a run of stores, computed into a local ahead of the whole run.

m2c writes each store with its value in place:

    p->kind = 0xF;  p->next = 0;  p->time = a->now + b->base->offset;  call(p);

GCC 2.7.2 schedules the sum's two loads after the stores that come before it in the source, so the loads' registers
and the stores' order follow the source. The game computed the sum first and stored after (`lw; lw; addu` ahead of the
three `sh`/`sw`), which a `temp = a->now + b->base->offset;` before the first store reproduces. Measured on a KMC GCC
2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) 25-instruction N64 voice-stop function: 305 -> 0 with the sum in a local, the
callee's name and the plain `do { } while (0)` debris of the earlier drafts cleaned.

The shape: in one block, a statement `STORE = [(type)] (A + B);` where both operands read memory (`M2C_FIELD(` or `*`),
preceded by one to three stores (`M2C_FIELD(base, ...) = value;`) that contain no call and whose bases the sum does not
read. One child per such sum and run length: a new local (`temp_sum`, typed as the cast or `s32`) set to `A + B`
before the run's first store, the stored value replaced by the local. `do { } while (0)` wrappers around a statement
are looked through. A candidate: the sum may read memory a store writes, so the judge decides.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view

FAMILY = 'sum_before_store_run'
FAMILIES = (FAMILY,)

OPEN = re.compile(r'\A(?:do\s*\{\s*)*')
CLOSE = re.compile(r'(?:\s*\}\s*while\s*\(\s*0\s*\)\s*;)*\Z')
STORE = re.compile(rf'\A(?P<lhs>M2C_FIELD\((?P<base>{IDENT}),[^;]*?\))\s*=\s*(?P<value>[^;]+?);\Z', re.S)
CAST = re.compile(r'\A\((?P<ty>[su](?:8|16|32))\)\s*')
CALL = re.compile(r'\b(?!M2C_FIELD\b)[A-Za-z_]\w*\s*\(')
MEMORY = re.compile(r'M2C_FIELD\(|\*\s*[A-Za-z_(]')
TYPES = {'s32', 'u32', 's16', 'u16', 's8', 'u8'}
RUN = 3


def _inner(clean, start, end):
    """(start, end) of the statement itself inside any `do { } while (0);` wrappers."""
    text = clean[start:end]
    lead = OPEN.match(text).end()
    tail = CLOSE.search(text, lead)
    return start + lead, start + tail.start() if tail else end


def _split_sum(text):
    """(left, right) of a top-level `+` of `(A + B)`, with both parts non-empty; None for anything else."""
    text = text.strip()
    if not (text.startswith('(') and text.endswith(')')):
        return None
    inner, depth, cut = text[1:-1], 0, None
    for at, char in enumerate(inner):
        depth += (char in '([') - (char in ')]')
        if depth == 0 and inner[at:at + 3] == ' + ' and cut is None:
            cut = at
        elif depth == 0 and inner[at] in '-*/<>?:|&' and at and inner[at - 1] == ' ':
            return None
    if cut is None:
        return None
    return inner[:cut], inner[cut + 3:]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    fresh = 'temp_sum'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    nl = clean.find('\n', part.opening) + 1
    indent_head = re.match(r'[ \t]*', source[nl:])[0] or '    '
    out = []
    for block_open, block_close in sorted(pairs.items()):
        units = statements(clean, block_open + 1, block_close)
        for index, (start, end) in enumerate(units):
            a, b = _inner(clean, start, end)
            store = STORE.match(clean[a:b])
            if not store or '{' in clean[a:b]:
                continue
            value_at = a + store.start('value')
            value = store['value']
            cast = CAST.match(value)
            body = value[cast.end():] if cast else value
            sides = _split_sum(body)
            if not sides or not all(MEMORY.search(side) for side in sides) or CALL.search(body):
                continue
            body_at = value_at + (cast.end() if cast else 0)
            bases = set()
            for back in range(1, RUN + 1):
                if index - back < 0:
                    break
                p, q = _inner(clean, *units[index - back])
                earlier = STORE.match(clean[p:q])
                if not earlier or '{' in clean[p:q] or CALL.search(earlier['value']):
                    break
                bases.add(earlier['base'])
                if any(re.search(rf'\b{base}\b', body) for base in bases):
                    break
                first = units[index - back][0]
                ty = cast['ty'] if cast and cast['ty'] in TYPES else 's32'
                line = source.rfind('\n', 0, first) + 1
                indent = re.match(r'[ \t]*', source[line:])[0]
                text = edit(source, [(body_at, body_at + len(body), fresh), (line, line, f'{indent}{fresh} = {body.strip()[1:-1]};\n'),
                                     (nl, nl, f'{indent_head}{ty} {fresh};\n')])
                if cast:
                    text = text.replace(f'= {cast.group(0)}{fresh};', f'= {fresh};', 1)
                if (FAMILY, text) not in out:
                    out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
