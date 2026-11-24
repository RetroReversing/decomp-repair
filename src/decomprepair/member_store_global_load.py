"""A store through a cast pointer that the target schedules after the next read of a plain global, written as a store
to a structure member: `(*(f32 *)((char *)(p) + 8)) = x; if (gObj != NULL)` as
`((struct { u8 pad[8]; f32 v; } *)(p))->v = x; if (gObj != NULL)`.

KMC GCC 2.7.2 (`-O2`, N64): both schedulers keep a store before a later load that may alias it. A store through
`*(T *)((char *)p + off)` is a plain scalar reference, so it may alias the global the next statement reads and the
global's `lw` stays after it. A store to a member of a structure is MEM_IN_STRUCT_P, and gcc 2.x's alias rule says a
structure reference through a varying address never aliases a scalar at a fixed address: the global's load moves
above the store (and the store fills the branch's delay slot, `beqz $v0, ...; swc1 $f0, 8($s2)`). A 2,503-instruction
projectile update (KMC GCC 2.7.2): 1200 -> 1180 for one store before `if (gTargetObject != NULL)`, then 1180 -> 1060
for two stores before a read of `gPlayerActor`; the pointer spelling alone (array index, casts) compiled the same.
The reading is from the output; the judge decides.

A site is a statement `(*(T *)((char *)(P) + OFF)) = E;` (or `+ 0`, or without the offset) whose next statement reads
a global the source or header declares `extern` as a scalar or a pointer (not an array or a function). Each site gives
a child with that store rewritten, one with the run of such stores through the same `P` right before it rewritten
too, and one child with every site's run. The address and the stored value are unchanged: the member sits at `OFF`
inside an anonymous structure cast from `P`.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'member_store_global_load'
FAMILIES = (FAMILY,)
LIMIT = 8
_TYPE = r'(?:u8|s8|u16|s16|u32|s32|f32|f64|int|short|char|float|double|unsigned(?:\s+(?:char|short|int))?|void\s*\*|' \
        + IDENT + r'\s*\*)'
_STORE = re.compile(r'(?m)^(?P<ind>[ \t]*)\(\*\(\s*(?P<type>' + _TYPE + r')\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*'
                    r'\(?\s*(?P<base>' + IDENT + r')\s*\)?\s*(?:\+\s*(?P<off>0x[0-9A-Fa-f]+|\d+)\s*)?\)\s*\)\s*'
                    r'=(?!=)(?P<value>[^;{}\n]*);[ \t]*\n')


def _globals(source, header):
    """Names declared `extern` as one scalar or pointer: no array, no function."""
    names = set()
    for text in (header or '', source):
        for found in re.finditer(r'(?m)^\s*extern\s+([^;()\[\]{}=]+?)\b(' + IDENT + r')\s*;', text):
            names.add(found.group(2))
    return names


def _next_statement(clean, i, hi):
    """The text of the statement (or `if`/`while` head) that starts at or after `i`."""
    j = i
    while j < hi and clean[j].isspace():
        j += 1
    end = j
    depth = 0
    while end < hi:
        c = clean[end]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0 and re.match(r'(?:if|while)\b', clean[j:end]):
                return clean[j:end + 1]
        elif c in ';{}' and depth == 0:
            return clean[j:end]
        end += 1
    return clean[j:end]


def _reads(statement, names):
    for found in re.finditer(r'(?<![\w.>&])(' + IDENT + r')\b(?!\s*\()', statement):
        if found.group(1) in names:
            return True
    return False


def _sites(source, name, header):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    names = _globals(source, header)
    if not names:
        return []
    stores = [m for m in _STORE.finditer(clean, lo, hi)]
    sites = []
    for k, found in enumerate(stores):
        if not _reads(_next_statement(clean, found.end(), hi), names):
            continue
        run = [found]
        for prev in reversed(stores[:k]):
            if prev.end() != run[0].start() or prev['base'] != found['base']:
                break
            run.insert(0, prev)
        sites.append(run)
    return sites


def _member(found, source):
    off = found['off'] or '0'
    kind = re.sub(r'\s+', ' ', found['type']).strip()
    pad = f'u8 pad[{off}]; ' if int(off, 0) else ''
    value = source[found.start('value'):found.end('value')].strip()
    return f"{found['ind']}((struct {{ {pad}{kind} v; }} *)({found['base']}))->v = {value};\n"


def _apply(source, stores):
    out = source
    unique = {m.start(): m for m in stores}  # runs of neighbouring sites share stores
    for found in sorted(unique.values(), key=lambda m: m.start(), reverse=True):
        out = out[:found.start()] + _member(found, source) + out[found.end():]
    return out


def variants(source, name, header=''):
    sites = _sites(source, name, header)
    picks, seen = [], set()
    for run in sites[:LIMIT]:
        for pick in ([run[-1]], run):
            key = tuple(m.start() for m in pick)
            if key not in seen:
                seen.add(key)
                picks.append(pick)
    if len(sites) > 1:
        picks.append([m for run in sites for m in run])
    return [(FAMILY, _apply(source, pick)) for pick in picks]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
