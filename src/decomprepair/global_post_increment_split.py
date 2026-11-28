"""A store at a post-incremented index that outlives the function, written as two statements: `a[g++] = v;` ->
`a[g] = v; g++;`.

`increment_expression_repairs` splits and joins the local-variable forms; a global (or member) counter was left as it
was. A 511-instruction N64 input recorder (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) appends a packed word to a buffer: the
target reloads the global index after computing the word, where `buffer[index++] = word;` reused the value the bounds
test had loaded (one `andi` more and the store of the index earlier). The split statement took the candidate from
750 to 0. Why the two spellings differ in the reload is not confirmed in the compiler source.

global_post_increment_split
    Each statement `A[G++] = E;` (or `G--`) where `G` is not declared in the function (a global) or is a member path,
    and `E` does not mention `G`: `A[G] = E; G++;`, one site at a time, then all together. The statement must be a
    full statement of a block, so no unbraced `if` body is split in two.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_post_increment_split'
FAMILIES = (FAMILY,)
LIMIT = 8

_PATH = rf'{IDENT}(?:(?:\.|->){IDENT})*'
_STORE = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<array>{_PATH})\s*\[\s*(?P<index>{_PATH})\s*(?P<step>\+\+|--)\s*\]'
                    rf'\s*=(?!=)\s*(?P<value>[^;{{}}]+);')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    signature = max(part.clean.rfind(name, 0, part.opening), 0)
    local = part.clean[signature:part.end]  # the parameters and the body, not the file's externs
    sites = []
    for hit in _STORE.finditer(part.clean, part.opening, part.end):
        index = hit['index']
        root = re.match(IDENT, index)[0]
        if root == index and re.search(rf'\b(?!return\b){IDENT}[\s*]+{re.escape(index)}\s*(?=[;=,)\[])', local):
            continue
        whole = re.compile(rf'(?<![\w.>]){re.escape(index)}(?!\w)')
        if whole.search(hit['value']) or whole.search(hit['array']):
            continue
        sites.append(hit)

    def build(chosen):
        edits = []
        for hit in chosen:
            start = hit.start('array')
            line = source.rfind('\n', 0, start) + 1
            separator = '\n' + source[line:start] if not source[line:start].strip() else ' '
            value = source[hit.start('value'):hit.end('value')]
            edits.append((start, hit.end(), f"{hit['array']}[{hit['index']}] = {value};{separator}"
                                            f"{hit['index']}{hit['step']};"))
        return edit(source, edits)

    out = [build([site]) for site in sites[:LIMIT]]
    if len(sites) > 1:
        out.append(build(sites))
    return [(FAMILY, text) for text in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
