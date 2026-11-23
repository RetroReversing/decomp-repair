"""A global cursor read ahead of an unrelated store, written after it.

A display-list builder reads the command cursor into a local (`p = gCursor;`, then `gCursor = p + 8;`) and fills the
command through that local. Between the read and the command's own words m2c leaves stores to *another* record (a
value word packed from the results of two calls). The first scheduler (`sched.c`) schedules each basic block backwards
and breaks ties by the load's latency, so a load of the cursor written ahead of such a store is hoisted to the head of
the block, right after the call, and takes a register the game's code used for the packed value. Written after the
store the load stays between the packing's `andi` and `sll`, as in the game: on a texture-load builder of 715
instructions (`gcc-2.7.2-kmc -O2 -G0 -mips3 -mgp32 -mfp32`) moving three such reads took 1060 to 880 and moving the
cursor read and its bump past the next packed store 585 to 465 (the pair of calls before it, in the other order, then
415; with the arms' cursor temporaries split, 0).

Offered where the program is unchanged unless the store writes the cursor global itself (the hypothesis; the judge
decides): a statement `P = G;` (P a local of the function, G an extern variable, an optional cast on G), optionally
followed by its bump `G = P + k;`, directly followed by one assignment through a pointer (`*(T *)(...) = e;` or
`((T *) q)->f = e;`) that names neither P nor G and holds no call.

`variants` gives, labelled `cursor_read_after_store`, one child per such site (the read, with its bump when it is
there, after the store) and one child with every site moved, because each site alone is a small change and the arms
repeat the same shape.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'cursor_read_after_store'
FAMILIES = (FAMILY,)
LIMIT = 12
ID = r'[A-Za-z_]\w*'
CAST = r'(?:\(\s*[A-Za-z_][\w\s*]*\)\s*)?'
READ = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<p>{ID})\s*=\s*{CAST}(?P<g>{ID})\s*;[ \t]*\n')
STORE = re.compile(r'(?m)^[ \t]*(?:\*\s*\(|\(\()[^;{}]*?[^=!<>]=(?!=)[^;{}]*;')
CALL = re.compile(r'[\w]\s*\(')


def _declared(body, name):
    return re.search(rf'(?m)^[ \t]*[A-Za-z_][\w\s*]*\b{re.escape(name)}\s*;', body) is not None


def _sites(part, source):
    body = part.clean[part.opening + 1:part.end - 1]
    sites = []
    for hit in READ.finditer(part.clean, part.opening + 1, part.end):
        p, g = hit['p'], hit['g']
        if p == g or not _declared(body, p) or _declared(body, g) \
                or not re.search(rf'\bextern\b[^;(]*\b{re.escape(g)}\s*;', source):
            continue
        at = hit.end()
        bump = re.compile(rf'[ \t]*{re.escape(g)}\s*=\s*{re.escape(p)}\s*\+[^;{{}}]*;[ \t]*\n').match(part.clean, at)
        if bump:
            at = bump.end()
        store = STORE.match(part.clean, at)
        if not store:
            continue
        text = part.clean[store.start():store.end()]
        if re.search(rf'\b(?:{re.escape(p)}|{re.escape(g)})\b', text) or CALL.search(text):
            continue
        sites.append((hit.start(), at, store.end()))
    return sites


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part, source)
    if not sites:
        return []

    def move(start, mid, end):
        # the store may be followed on its line by the `}` of the block the read sits in: only the statements move
        indent = re.match(r'[ \t]*', source[start:mid])[0]
        return (start, end, indent + source[mid:end].strip() + '\n' + source[start:mid].rstrip('\n'))

    out = [edit(source, [move(*s)]) for s in sites]
    if len(sites) > 1:
        out.append(edit(source, [move(*s) for s in sites]))
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 66}
