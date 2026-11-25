"""A local the function sets and finishes with before its first loop, and sets afresh inside the loop, given a local of
its own for the entry web.

On a 485-instruction N64 audio thread (SN64 GCC 2.8.1) the entry code read `h = init(); setup(); report(fmt, h);` and
the message loop reused `h` for later call results. One variable is one pseudo: its references inside the loop gave it
a high priority, and global.c put the entry value in `$s1` where the target has `$s0` (the register the loop's message
argument takes, which the entry value never meets). With the entry web in its own local the two rows went away
(25060 -> 25050, every register row gone). A hypothesis from global.c's priority order; the judge decides.

entry_web_split
    For a local declared at the top of the function, assigned before the function's first loop with every mention
    before the loop, and whose first mention inside the loop is a plain assignment, one child renames the mentions
    before the loop to a new local of the same type.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'entry_web_split'
FAMILIES = (FAMILY,)
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>(?:(?:unsigned|signed|const|volatile|struct)\s+)*{IDENT}[\s*]+?)'
                   rf'(?P<name>{IDENT})\s*;[ \t]*$')
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _fresh(clean, name):
    for suffix in ('_entry', '_0', '_1', '_2'):
        candidate = name + suffix
        if not re.search(rf'\b{re.escape(candidate)}\b', clean):
            return candidate
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body_start = part.opening + 1
    loop = _LOOP.search(clean, body_start, part.end)
    if not loop:
        return []
    out = []
    for decl in _DECL.finditer(clean, body_start, loop.start()):
        local = decl['name']
        if decl['type'].strip() in ('return', 'goto', 'break', 'continue'):
            continue
        token = re.compile(rf'(?<![\w.>]){re.escape(local)}\b')
        before = [m for m in token.finditer(clean, decl.end(), loop.start())]
        inside = [m for m in token.finditer(clean, loop.start(), part.end)]
        if not before or not inside:
            continue
        if not re.match(r'\s*=(?!=)', clean[before[0].end():]):
            continue
        if not re.match(r'\s*=(?!=)', clean[inside[0].end():]):
            continue
        fresh = _fresh(clean, local)
        if not fresh:
            continue
        declaration = (decl.end(), decl.end(), f'\n{decl["indent"]}{decl["type"]}{fresh};'
                       if decl['type'].endswith('*') else f'\n{decl["indent"]}{decl["type"].rstrip()} {fresh};')
        edits = [declaration] + [(m.start(), m.end(), fresh) for m in before]
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
