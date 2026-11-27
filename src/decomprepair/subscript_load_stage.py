"""An array load that indexes another array, written into a local first, preferably one a later loop reuses.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`) function that copies, for each of eight records, the entry
the record's own selector byte picks: `out[j] = T[i][j][T[i][j][0] + 2];`. Written in one expression the selector's
load lives in a block-local register and the address sums come out in another order; the target loads it into the
register of the loop counter the code starts a few lines later, because the game wrote `k = T[i][j][0];` and used the
same `k` for that search loop (755 -> 0).

subscript_load_stage
    In one assignment, an array element read inside another element's index is read into a local first. One child per
    (load, local): a function-level integer local that the statement does not name and that is written before every
    read after it, and in every enclosing loop's body, or else one new local. Hypothesis from the match, not from the
    compiler source: a name that also counts a later loop gives global.c one pseudo for both values.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .guarded_loop_for import _written_before_read
from .integer_repair_support import DECL, edit, view

FAMILY = 'subscript_load_stage'
FAMILIES = (FAMILY,)
LIMIT = 12
PER_LOAD = 4
NEW_LOCAL = '__repair_index'
_WIDE = ('s32', 'int', 'u32', 'unsigned int')
# a plain assignment statement: the first thing on its line, no call before the `=`, ending in `;`
_STATEMENT = re.compile(r'(?m)^[ \t]*(?P<text>[^\s;{}][^;{}=\n()]*=(?!=)[^;{}]*;)')
_LOOP_HEADER = re.compile(r'^(?:for|while|do)\b')
_BASE = re.compile(r'(?<![\w.>])[A-Za-z_]\w*\s*\[')


def _nested_loads(text):
    """(start, end) of every `a[..]...[..]` that sits inside another subscript's brackets."""
    found = []
    for base in _BASE.finditer(text):
        before = text[:base.start()]
        if before.count('[') <= before.count(']') or before.rstrip().endswith('&'):
            continue
        end = close(text, base.end() - 1, '[', ']')
        while end >= 0:
            following = re.compile(r'\s*\[').match(text, end + 1)
            if not following:
                break
            end = close(text, following.end() - 1, '[', ']')
        if end >= 0:
            found.append((base.start(), end + 1))
    return found


def _free(clean, name, start, stop, low, high):
    """`name` holds nothing needed across the statement [start, stop)."""
    if re.search(rf'\b{re.escape(name)}\b', clean[start:stop]) or re.search(rf'&\s*{re.escape(name)}\b', clean[low:high]):
        return False
    if not _written_before_read(clean, stop, low, high, name):
        return False
    block = enclosing_block(clean, start, low)
    while block >= 0:
        if _LOOP_HEADER.match(header_before(clean, block)):
            last = close(clean, block)
            if last < 0 or not _written_before_read(clean, block + 1, block + 1, last, name):
                return False
        block = enclosing_block(clean, block, low)
    return True


def variants(source, name, header=''):
    part = view(source, name)
    if not part or NEW_LOCAL in source:
        return []
    clean, low, high = part.clean, part.opening + 1, part.end
    locals_ = [m['name'] for m in DECL.finditer(clean, low, high)
               if re.sub(r'\s+', ' ', m['type']) in _WIDE and enclosing_block(clean, m.start(), low) < 0]
    children = []
    for statement in _STATEMENT.finditer(clean, low, high):
        start, stop = statement.span('text')
        # a statement standing alone as the body of a braceless `if` or loop cannot be split in two
        if not clean[:start].rstrip().endswith((';', '{', '}')):
            continue
        text = clean[start:stop]
        indent = source[source.rfind('\n', 0, start) + 1:start]
        seen = set()
        for first, last in _nested_loads(text):
            load = source[start + first:start + last]
            if load in seen:
                continue
            seen.add(load)
            spots = [(a, b) for a, b in _nested_loads(text) if source[start + a:start + b] == load]
            free = [local for local in locals_ if _free(clean, local, start, stop, low, high)]
            for local in free[:PER_LOAD] or [NEW_LOCAL]:
                changes = [(start, start, f'{local} = {load};\n{indent}')]
                changes += [(start + a, start + b, local) for a, b in spots]
                if local == NEW_LOCAL:
                    changes.append((low, low, f'\n  s32 {NEW_LOCAL};'))
                children.append((FAMILY, edit(source, changes)))
    return children[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
