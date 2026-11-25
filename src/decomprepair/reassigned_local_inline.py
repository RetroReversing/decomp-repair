"""A local's first value, read only by the test right after it and then assigned again, written into that test.

m2c (and an agent keeping its output) writes `id = (u8) action; if (... | (id == 25)) return 0;` and a few statements
later `id = (u8) action;` again for the code that follows. The assignment before the test gives `id` its first
set there: a pseudo with two sets, which GCC 2.7.2's first scheduler does not treat as a "birthing" insn (sched.c
`birthing_insn_p` needs `reg_n_sets == 1`), so the extension is launched ahead of the arithmetic beside it, and the
allocator colours the two lives as one pseudo. Written into the test (`(u8) action == 25`) the extension is an
anonymous single-set pseudo that stays where the source puts it, and the second assignment is the local's only set. A
rotating-slot lookup (KMC GCC 2.7.2, `-O2 -G0 -mips3`) stood at 65 with the other steps in place and at 20 with this
one, the remaining rows a scheduling order, an operand order and a register; the compiler-source reading is a
hypothesis that the measurement agrees with, and the judge decides each child.

The child (`reassigned_local_inline`, one per qualifying assignment, bounded) removes `V = E;` and writes `(E)` for `V`
in the statement that follows, when:
- `E` reads only parameters and locals (no call, memory read, address, increment or assignment) and none of them is
  assigned inside that statement;
- every use of `V` before its next assignment (or the end of the function) is in that one statement, which is an `if`
  condition or a single `;` statement, and the next assignment, if any, is a plain `V = ...;`;
- no loop, and no `goto` back to an earlier label, can come round to the assignment again.
"""
import re

from .csource import _blank, find

FAMILY = 'reassigned_local_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
TYPES = {'u8', 's8', 'u16', 's16', 'u32', 's32', 'u64', 's64', 'char', 'short', 'int', 'long', 'unsigned', 'signed',
         'f32', 'f64', 'float', 'double', 'void'}


def _python_match(clean, open_at):
    depth = 0
    for index in range(open_at, len(clean)):
        depth += clean[index] == '(' or clean[index] == '{'
        depth -= clean[index] == ')' or clean[index] == '}'
        if depth == 0:
            return index
    return -1


_match = _python_match
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _match(clean, open_at):
        found = _scan.close_pairs(clean, open_at, '({', ')}', False, True, -1)
        return _python_match(clean, open_at) if found is NotImplemented else found


def _in_loop(clean, opening, position):
    """A loop (or a back-jump) that can come round to `position` again."""
    stack = []
    for index in range(opening, position):
        if clean[index] == '{':
            stack.append(index)
        elif clean[index] == '}' and stack:
            stack.pop()
    for brace in stack:
        header = clean[max(clean.rfind(';', 0, brace), clean.rfind('{', 0, brace), clean.rfind('}', 0, brace)) + 1:brace].strip()
        if re.search(r'\b(?:for|while)\s*\(', header):
            return True
        if re.search(r'\bdo$', header):
            close = _match(clean, brace)
            tail = re.match(r'\s*while\s*\(\s*([^)]*?)\s*\)', clean[close + 1:]) if close > 0 else None
            if not tail or tail[1] != '0':
                return True
    gotos = set(re.findall(rf'\bgoto\s+({IDENT})\s*;', clean[position:]))
    return any(re.search(rf'(?<![\w.]){label}\s*:(?!:)', clean[opening:position]) for label in gotos)


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    known = set(re.findall(rf'\b{IDENT}\b', clean[start:opening])) | set(
        re.findall(rf'\b(?:{"|".join(TYPES)})\s+\**\s*({IDENT})\s*[;=,\[]', clean[opening:end]))
    result = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}=]+);', clean[opening:end]):
        var, value = hit[1], hit['value'].strip()
        begin, stop = opening + hit.start(), opening + hit.end()
        if var not in known or var in TYPES or clean[opening:begin].rstrip()[-1:] not in {'{', ';', '}'}:
            continue
        names = set(re.findall(IDENT, value)) - TYPES
        if not names or var in names or not names <= known or re.search(r'\w\s*\(|\[|->|&|\+\+|--|[^=!<>]=[^=]|(?<![\w)])\*', value):
            continue
        condition = re.match(r'\s*if\s*\(', clean[stop:end])
        if condition:
            last = _match(clean, stop + condition.end() - 1)
        else:
            last = clean.find(';', stop)
            if last < 0 or re.search(r'[{}]', clean[stop:last]):
                continue
        if last < 0 or not re.search(rf'(?<![\w.>]){var}\b', clean[stop:last]):
            continue
        piece = clean[stop:last + 1]
        if re.search(rf'(?<![\w.>])(?:{var}|{"|".join(re.escape(n) for n in names)})\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\+\+|--', piece):
            continue
        after = re.compile(rf'(?<![\w.>]){var}\b').search(clean, last + 1, end)
        if after and not re.match(r'\s*=(?!=)', clean[after.end():]):
            continue
        if _in_loop(clean, opening, begin):
            continue
        inner = source[stop:last + 1]
        replaced = re.sub(rf'(?<![\w.>]){var}\b', lambda _m, value=value: f'({value})', inner)
        text = source[:begin] + replaced.lstrip(' ') + source[last + 1:]
        if text != source and text not in result:
            result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
