"""A global array the draft declared `volatile` that the function only indexes, as the plain array the game had.

`extern volatile s16 table[4];` is what a search leaves behind to keep one store in program order: it works, and it
hides the real addressing. A volatile element is not folded into the `%lo()` of its address, so the store is written
`lui; addiu; addu; sh 0($v1)` where the game's plain array gives `lui $at; addu $at,$at,$v0; sh %lo(table)($at)`,
and the volatile store is a scheduling barrier a plain one is not (`gcc-2.7.2-kmc`, a save-slot reset loop: with the
volatile the diff kept an extra `addiu`, an `$a0`/`$a1` pair swapped and a store hoisted past the next load; without
it only registers differed). The scalar form (`volatile_global_plain`) rewrites casts through a volatile scalar; this
is the array that is only ever written `name[index]`.

Offered for each `extern volatile T name[...];` (or `T volatile`) that the function mentions and that is never
used without an index (no `&name`, no bare `name` passed on): one child with the qualifier dropped
(`volatile_array_plain`), and when several arrays qualify, a child dropping all of them. A hypothesis; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'volatile_array_plain'
FAMILY_ALL = 'volatile_array_plain_all'
FAMILIES = (FAMILY, FAMILY_ALL)
LIMIT = 6
DECLARATION = re.compile(rf'(?m)^(?P<pre>[ \t]*extern[ \t]+)(?:volatile[ \t]+(?P<type>[A-Za-z_][\w \t\*]*?)|(?P<type2>[A-Za-z_][\w \t\*]*?)[ \t]+volatile)'
                         rf'[ \t]+(?P<name>{IDENT})[ \t]*\[(?P<size>[^\]]*)\][ \t]*;')


def _only_indexed(body, glob):
    for hit in re.finditer(rf'(?<![\w.]){re.escape(glob)}\b', body):
        after = body[hit.end():].lstrip()
        if not after.startswith('['):
            return False
    return not re.search(rf'&\s*{re.escape(glob)}\b', body)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    found = []
    for decl in DECLARATION.finditer(clean[:part.opening]):
        glob = decl['name']
        if not re.search(rf'(?<![\w.]){re.escape(glob)}\b', body) or not _only_indexed(body, glob):
            continue
        kind = (decl['type'] or decl['type2']).strip()
        found.append((decl, f"{decl['pre']}{kind} {glob}[{decl['size']}];"))
    found = found[:LIMIT]
    out = [(FAMILY, edit(source, [(d.start(), d.end(), text)])) for d, text in found]
    if len(found) > 1:
        out.append((FAMILY_ALL, edit(source, [(d.start(), d.end(), text) for d, text in found])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
