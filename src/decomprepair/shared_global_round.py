"""One global rounded up twice, written as the buffer's own variable holding it first.

A loader that carves two buffers from one heap pointer keeps the pointer in the first buffer's variable, computes the
second from it, then rounds the first in place:

    buffer = heap;
    table = ((u32) (buffer + 0x7D0F) >> 4) * 0x10;
    buffer = ((u32) (buffer + 0xF) >> 4) * 0x10;

m2c names the global in both expressions, `buffer = ((u32) (heap + 0xF) >> 4) * 0x10;
table = ((u32) (heap + 0x7D0F) >> 4) * 0x10;`, and the loaded word then goes to a scratch register instead of the
buffer's saved one. One result per function so far (an SN-N64 2.81, GCC 2.8.1 `-O2`, 212-instruction asset loader:
one of the edits between m2c's draft and the exact C), so why the compiler wants it is a hypothesis.

shared_global_round
    Two adjacent round-ups of the same plain global (the one with the smaller offset is the buffer) rewritten as above.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'shared_global_round'
FAMILIES = (FAMILY,)

_IDENT = r'[A-Za-z_]\w*'
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'


def _round(tag):
    return (rf'(?P<indent{tag}>[ \t]*)(?P<y{tag}>{_IDENT}) = \(\(u32\) \((?P<g{tag}>{_IDENT}) \+ '
            rf'(?P<k{tag}>{_NUMBER})\) >> (?P<n{tag}>{_NUMBER})\) (?P<back{tag}>\* {_NUMBER}|<< {_NUMBER});\n')


_PAIR = re.compile('(?m)^' + _round('1') + _round('2'))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, low, high = part.clean, part.opening, part.end
    out = []
    for hit in _PAIR.finditer(clean, low, high):
        shared = hit['g1']
        first, second = hit['y1'], hit['y2']
        if (shared != hit['g2'] or first == second or shared in (first, second)
                or hit['n1'] != hit['n2'] or hit['back1'] != hit['back2']):
            continue
        # a global: declared extern outside the function, never a local or a parameter
        if not re.search(rf'\bextern\b[^;()\[\]]*\b{shared}\s*;', clean[:low] + clean[high:]):
            continue
        small, large = ('1', '2') if int(hit['k1'], 0) <= int(hit['k2'], 0) else ('2', '1')
        buffer = hit[f'y{small}']
        indent = hit['indent1']

        def line(tag, hit=hit, indent=indent, buffer=buffer):
            return (f'{indent}{hit["y" + tag]} = ((u32) ({buffer} + {hit["k" + tag]}) >> {hit["n" + tag]}) '
                    f'{hit["back" + tag]};\n')

        text = f'{indent}{buffer} = {shared};\n{line(large)}{line(small)}'
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), text)])))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
