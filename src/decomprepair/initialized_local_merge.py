"""Two locals declared with their values (`u16 h = f(x);`) whose lives never overlap, written as one variable.

The merge families (`disjoint_local_merge`, `disjoint_scalar_merge`) read plain `type name;` declarations, so a
source written in blocks, each local declared with its first value, offers them nothing: the pair they would merge is
invisible. The game often had one variable there. A 179-instruction N64 function (`gcc-2.7.2-kmc -O1`) kept one
effect handle for a call before its loop and for the call inside it; written as `u16 h = ...;` in the outer block and
`u16 h2;` in the loop body the allocator spent a sixth saved register and 8 more bytes of frame (325), and one `h`
was exact (0). A controlled result of one function.

The child splits every initialiser of a declaration run into `type name;` declarations followed by the assignments in
the same order (C89 needs the declarations first; the compiler emits the same code for both spellings), then lets the
merge families work on that source. A candidate rewrite; the exact judge decides.
"""
import re

from . import disjoint_local_merge_repairs, disjoint_scalar_merge
from .integer_repair_support import IDENT, view

FAMILY = 'initialized_local_merge'
FAMILIES = (FAMILY,)
LIMIT = 16

_DECL = re.compile(rf'(?P<lead>\s*)(?P<type>(?:(?:unsigned|signed|struct|union|enum)\s+)?{IDENT})(?P<gap>(?:\s|\*)+)'
                   rf'(?P<name>{IDENT})(?P<rest>\s*(?:=\s*(?P<init>[^;{{}}]+))?;)')
_NOT_TYPES = {'return', 'goto', 'case', 'else', 'do', 'break', 'continue', 'sizeof', 'static', 'const', 'extern',
              'register', 'volatile', 'typedef'}


def _top_level_comma(text):
    depth = 0
    for char in text:
        depth += char in '(['
        depth -= char in ')]'
        if char == ',' and not depth:
            return True
    return False


def split(source, name):
    """The source with each block's initialised declarations split, or None when there is none to split."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    edits = []
    for opening in [at for at in range(part.opening, part.end) if clean[at] == '{']:
        at, run = opening + 1, []
        while True:
            hit = _DECL.match(clean, at)
            if not hit or hit['type'].split()[0] in _NOT_TYPES or (hit['init'] and _top_level_comma(hit['init'])):
                break
            run.append(hit)
            at = hit.end()
        initialised = [hit for hit in run if hit['init']]
        if not initialised:
            continue
        indent = run[0]['lead'].rsplit('\n', 1)[-1]
        assignments = []
        for hit in initialised:
            edits.append((hit.end('name'), hit.end('rest'), ';'))
            value = source[hit.start('init'):hit.end('init')].strip()
            assignments.append(f"\n{indent}{hit['name']} = {value};")
        edits.append((run[-1].end(), run[-1].end(), ''.join(assignments)))
    if not edits:
        return None
    # right to left; at one position the replaced declaration's `;` goes in before the assignments that follow it
    for start, end, text in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    plain = split(source, name)
    if plain is None:
        return []
    children = [child for _, child in disjoint_local_merge_repairs.variants(plain, name)]
    children += [child for _, child in disjoint_scalar_merge.variants(plain, name)]
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != plain][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 98}  # the registry: no caller wiring (registry.py)
