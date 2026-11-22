"""A one-use temporary of a loaded shift, folded into the accumulator its product starts.

m2c writes a chain of scaled products with a temporary for the first link, `t = (*p >> 7); acc = t * X;`, and the
links after it in place, `acc = (acc >> 7) * Y;`. The original had all of them in place, `acc = *p; acc = (acc >> 7)
* X; acc = (acc >> 7) * Y;`: one pseudo for the whole chain, where the temporary is a pseudo of its own that the
allocator treats as a second quantity with its own priority (it moved the product's register and the load's). Measured
on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 4405 -> 3865. Offered when the
statement after the product has the in-place form of the same shift. Up to four one-line statements that mention
neither name and call nothing may stand between the temporary and its product (m2c put the record's next two loads
there, 205 on the same function); the load then comes first and the first product either right after it or where it was. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply

FAMILY = 'accumulator_chain'
FAMILIES = (FAMILY,)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    pattern = re.compile(r'(?P<i>[ \t]*)(?P<t>[A-Za-z_]\w*) = \((?P<load>.*?) >> (?P<n>\d+)\);[ \t]*\n'
                         r'(?P<mid>(?:[ \t]*[^\n{};]*;[ \t]*\n){0,4})'
                         r'[ \t]*(?P<a>[A-Za-z_]\w*) = (?P=t) \* (?P<x>[^;]*);')
    for hit in pattern.finditer(part.clean, part.opening, part.end):
        tail = part.clean[hit.end():hit.end() + 160]
        if not re.match(rf'\s*{re.escape(hit["a"])} = \({re.escape(hit["a"])} >> {hit["n"]}\) \*', tail):
            continue
        mid = hit['mid']
        if mid and (re.search(rf'(?<![\w.>])(?:{re.escape(hit["t"])}|{re.escape(hit["a"])})\b', mid)
                    or re.search(r'\b[A-Za-z_]\w*\s*\(', re.sub(r'\(\s*(?:[su](?:8|16|32)|char|f32)\s*\**\s*\)', '', mid))):
            continue
        indent = hit['i']
        load = hit['load']
        if load.startswith('(') and load.endswith(')') and load[1] == '*':
            load = load[1:-1]
        if not load.startswith('*'):
            continue
        first = f'{hit["a"]} = {load};\n'
        product = f'{indent}{hit["a"]} = ({hit["a"]} >> {hit["n"]}) * {hit["x"]};'
        mid_source = source[hit.start('mid'):hit.end('mid')]
        out.append((FAMILY, apply(source, [(hit.start() + len(indent), hit.end(), first + mid_source + product)])))
        if mid:
            # the load and its first product together ahead of the statements between them (the order the chain had)
            out.append((FAMILY, apply(source, [(hit.start() + len(indent), hit.end(),
                                                first + product + '\n' + mid_source.rstrip('\n'))])))
    return out
