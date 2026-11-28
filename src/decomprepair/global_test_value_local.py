"""A global tested and then set, its old value held in a local of the test's own block.

    if (busy != 1) {                {
        started = 1;                    int previous = busy;
    }                       ->          if (previous != 1) {
    busy = 1;                               started = 1;
                                        }
                                    }
                                    busy = 1;

The two compile to the same instructions in the same order. What differs is how long the global's high-address
register lives: the local's block puts the end of its scope between the load and the store (hypothesis: the block
note counts in the instruction numbering loop.c measures lifetimes with). Inside a loop, loop.c moves an address out
only when `threshold * savings * lifetime` reaches the loop's size, with the threshold falling after each move, so the
first few such latches of a loop body are moved with the local and not without it. A moved address that finds no
register is rematerialised into a reload register (`lui $t1, %hi(busy)` where we had `lui $v0`). SN64 GCC 2.8.1 `-O2`,
a 435-instruction hit search with eight cooldown latches, the first two written this way: 385 -> 10 (the loop dump
shows both addresses moved; each latch's lifetime one or more instructions longer).

Because the threshold falls in program order, the children are the first sites together, all of them, and each alone.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'global_test_value_local'
FAMILIES = (FAMILY,)
LIMIT = 12
PREFIX = 5

_IF = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<name>{IDENT})\s*(?P<test>(?:==|!=|<=|>=|<|>)\s*-?(?:0[xX][0-9a-fA-F]+|\d+)'
    r'[uU]?)\s*\)\s*\{')
_TYPE_WORD = r'(?:unsigned|signed|char|short|int|long|[su](?:8|16|32)|[A-Z]\w*)'


def _global_type(text, name):
    """The type of an `extern` integer scalar, alone or in a list of names; None for a pointer, array or volatile."""
    for found in re.finditer(rf'\bextern\s+((?:{_TYPE_WORD}\s+)*{_TYPE_WORD})\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*;', text):
        if name in re.findall(IDENT, found.group(2)):
            return found.group(1)
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    declarations = header + '\n' + source
    taken = set(re.findall(r'\bprevious_value\d+\b', source))
    sites = []
    for m in _IF.finditer(part.clean, part.opening, part.end):
        tested = m.group('name')
        stop = close(part.clean, m.end() - 1, '{', '}')
        kind = _global_type(declarations, tested)
        if not stop or not kind:
            continue
        if not re.match(rf'\s*{tested}\s*=(?!=)', part.clean[stop:part.end]):
            continue  # only a latch: the global is set right after the test
        sites.append((m, stop, kind))
    names = [f'previous_value{n}' for n in range(len(sites) + len(taken) + 1) if f'previous_value{n}' not in taken]

    def apply(chosen):
        text = source
        for index in sorted(chosen, reverse=True):
            m, stop, kind = sites[index]
            indent, local = m.group('indent'), names[index]
            inner = indent + '    '
            body = source[m.end() - 1:stop].replace('\n', '\n    ')
            block = (f'{indent}{{\n{inner}{kind} {local} = {m.group("name")};\n'
                     f'{inner}if ({local} {m.group("test")}) {body}\n{indent}}}')
            text = text[:m.start()] + block + text[stop:]
        return FAMILY, text

    count = len(sites)
    picks = [tuple(range(n)) for n in range(2, min(count, PREFIX + 1))]
    picks += [tuple(range(count))] if count > 1 else []
    picks += [(index,) for index in range(count)]
    return [apply(pick) for pick in picks[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
