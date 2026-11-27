"""Successive pointer results tested and filled through one scratch local, each kept under its own name.

m2c gives every call result a variable of its own and uses it for the test and every store:

    first = make();                         obj = make();
    if (first != NULL) {                    first = obj;
        first->kind = 1;                    if (obj != NULL) {
    }                                           obj->kind = 1;
    second = make();                        }
    if (second != NULL) {                   obj = make();
        second->prev = first;               second = obj;
    }                                       if (obj != NULL) { obj->prev = first; }

One variable that live across the later calls takes a saved register for the test and every store, where the target
moves the result into an argument register (`move $a0, $v0; beqz $a0` with `move $s2, $a0` in the slot), stores through
it, and keeps the saved copy only for what reads it later. On a 107-instruction constructor of three linked objects
(SN GCC 2.8.1, -O2) this one edit took the plain draft from 2315 to 1380 and was the step the other repairs needed.
That the short scratch's register comes from its dying at every call is a hypothesis; the judge decides.

shared_result_scratch
    Two or more `P = f(..);` statements, each followed (after at most three statements that do not name P) by
    `if (P != NULL) {` / `!= 0` / `(P)`, where every P is a pointer local of one declared type assigned only there. One
    child per type: a new local of that type receives each call, `P = scratch;` follows it (left out, with P's
    declaration, when nothing outside the guard names P), and the test and the guarded block read the scratch."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_result_scratch'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
SCRATCH = 'shared_result'
_SITE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<var>{IDENT})[ \t]*=[ \t]*(?P<call>{IDENT}[ \t]*\([^;{{}}]*\))[ \t]*;'
                   rf'(?P<between>(?:\s*[^;{{}}\n]+;){{0,3}}?)'
                   rf'\s*if\s*\(\s*(?P=var)\s*(?:!=\s*(?:NULL|0)\s*)?\)\s*\{{')


def _named(var):
    return re.compile(rf'(?<![\w.])(?<!->){re.escape(var)}\b')


def _sites(clean, opening, end):
    """(match, arm end, declaration match) for each guarded call result that one scratch could receive."""
    body = clean[opening:end]
    found = []
    for hit in _SITE.finditer(body):
        var = hit['var']
        arm_open = hit.end() - 1
        arm_end = close(body, arm_open, '{', '}')
        declaration = re.search(rf'(?m)^[ \t]*(?P<type>(?:struct[ \t]+)?{IDENT}[ \t]*\*+)[ \t]*{re.escape(var)}[ \t]*;'
                                rf'[ \t]*\n', body)
        if not arm_end or not declaration or _named(var).search(hit['between']):
            continue
        writes = re.findall(rf'(?<![\w.>*]){re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(var)}\b'
                            rf'|\b{re.escape(var)}\s*(?:\+\+|--)|&\s*{re.escape(var)}\b(?!\s*(?:->|\[))', body)
        if len(writes) != 1:
            continue
        found.append((hit, arm_end, declaration))
    return found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end] or re.search(rf'\b{SCRATCH}\b', clean):
        return []
    groups = {}
    for site in _sites(clean, opening, end):
        groups.setdefault(re.sub(r'\s+', '', site[2]['type']), []).append(site)
    result = []
    for sites in groups.values():
        if len(sites) < 2 or any(a[1] > b[0].start() for a, b in zip(sites, sites[1:])):
            continue
        result.append((FAMILY, _rewrite(source, clean, opening, end, sites)))
        if len(result) >= LIMIT:
            break
    return result


def _rewrite(source, clean, opening, end, sites):
    body = source[opening:end]
    blank = clean[opening:end]
    edits = []  # (start, end, replacement) over the body, none overlapping
    for hit, arm_end, declaration in sites:
        var = hit['var']
        named = _named(var)
        kept = any(not (hit.start() <= use.start() < arm_end or declaration.start() <= use.start() < declaration.end())
                   for use in named.finditer(blank))
        newline = '\n' + hit['indent']
        copy = f'{newline}{var} = {SCRATCH};' if kept else ''
        between = body[hit.start('between'):hit.end('between')]
        edits.append((hit.start('var'), hit.end('call'), f'{SCRATCH} = {body[hit.start("call"):hit.end("call")]}'))
        edits.append((hit.end('call'), hit.start('between'), ';' + copy))
        for use in named.finditer(blank, hit.start('between') + len(between), arm_end):
            edits.append((use.start(), use.end(), SCRATCH))
        if not kept:
            edits.append((declaration.start(), declaration.end(), ''))
    first = sites[0][2]
    pointer = first['type'].strip()
    gap = '' if pointer.endswith('*') else ' '
    indent = re.match(r'[ \t]*', blank[first.start():])[0]
    edits.append((first.start(), first.start(), f'{indent}{pointer}{gap}{SCRATCH};\n'))
    for start, stop, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        body = body[:start] + text + body[stop:]
    return source[:opening] + body + source[end:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
