"""One statement inside a loop wrapped in a one-shot scope (`do { STMT } while (0);`), so the variables it names gain a
loop-depth reference each and outrank a neighbour in global allocation.

On a 1713-instruction N64 bit-stream decoder (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ... -mfp32`) the source had
the target's instructions everywhere and only register rows were left: the cursor `p` took `$t0` where the target
gives it `$t1`, and a decoded field `sz` (with the clamped width that shares its register) took `$t1`. global.c
allocates in the order of `floor_log2 (refs) * refs / live_length`, refs weighted by loop depth (flow.c): `p` ranked
1.836 (416 / 1813) against `sz` 1.798 (74 / 247), so `sz` needed two more weighted references. A one-shot scope adds
one loop level to the references of the statements inside it and emits nothing; wrapping the field's read (a
function-like macro, `BITS(sz, n2);`) gave `sz` 1.846 and the registers came back (1285 -> 280); the next swap, a field
`y` against the loop's row offset, closed the same way with the scope around its store `o->cur[j].v[1] = y;`
(280 -> 0). Each scope is one child, so a greedy chain finds both; wrapping every statement of a variable at once
(local_weight_ladder) lifts its neighbours too.

macro_statement_scope
    A statement on its own line inside a `for`/`while`/`do` loop that invokes a function-like macro the source defines
    (`NAME(args);`): wrapped in `do { } while (0);`. One child per statement.
store_value_scope
    A store of a plain local on its own line inside a loop (`lhs = v;`, `lhs += v;` etc., `lhs` a member or element
    access): wrapped likewise. One child per statement.

Hypothesis from that match (flow.c's loop-depth weights, global.c's priority); the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

MACRO_FAMILY = 'macro_statement_scope'
STORE_FAMILY = 'store_value_scope'
FAMILIES = (MACRO_FAMILY, STORE_FAMILY)
LIMIT = 24
_MACRO_DEF = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+({IDENT})\(')
_MACRO_USE = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{IDENT})\s*\([^;{{}}]*\)\s*;[ \t]*$')
_STORE = re.compile(rf'^(?P<indent>[ \t]*)(?P<lhs>[^=;{{}}]*(?:->|\[|\.)[^=;{{}}]*?)\s*'
                    rf'(?:[-+*&|^]|<<|>>)?=(?!=)\s*(?P<value>{IDENT})\s*;[ \t]*$')
_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'sizeof', 'goto', 'break', 'continue'}


def _loop_bodies(clean, lo, hi):
    """(opening, end) of every braced loop body between lo and hi."""
    for hit in re.finditer(r'\b(?:for|while)\s*\(|\bdo\s*{', clean[:hi]):
        if hit.start() < lo:
            continue
        if hit[0].startswith('do'):
            opening = hit.end() - 1
        else:
            after = close(clean, hit.end() - 1)
            brace = after and re.match(r'\s*{', clean[after:hi])
            if not brace:
                continue
            opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if end and not re.match(r'\s*while\s*\(\s*0\s*\)', clean[end:hi]):
            yield opening, end


def _locals(clean, part):
    head = clean[:part.opening]
    text = head[head.rfind('(') + 1:] + clean[part.opening:part.end]
    return set(re.findall(rf'(?:^|[;{{}},(])\s*(?:register\s+)?(?:(?:unsigned|signed|const)\s+)*{IDENT}[\s*]+'
                          rf'({IDENT})\s*(?=[;=,)\[])', text))


def _sites(source, header, part):
    clean = part.clean
    macros = set(_MACRO_DEF.findall(header or '')) | set(_MACRO_DEF.findall(source[:part.opening]))
    locals_ = _locals(clean, part) - _KEYWORDS
    bodies = list(_loop_bodies(clean, part.opening, part.end))
    sites = {MACRO_FAMILY: [], STORE_FAMILY: []}
    at = part.opening + 1
    for line in source[part.opening + 1:part.end].splitlines(keepends=True):
        start, at = at, at + len(line)
        if not any(lo < start < hi for lo, hi in bodies):
            continue
        before = clean[:start].rstrip()
        if before[-1:] not in (';', '{', '}') or re.search(r'\b(?:else|do)\s*$', before):
            continue
        if re.search(r'\bdo\s*{\s*$', before) and re.match(r'\s*}\s*while\s*\(\s*0\s*\)', clean[at:part.end]):
            continue
        text = clean[start:at].rstrip('\n')
        use = _MACRO_USE.match(text)
        if use and use['name'] in macros:
            sites[MACRO_FAMILY].append((start, start + len(text), use['indent']))
            continue
        store = _STORE.match(text)
        if store and store['value'] in locals_ and not set(re.findall(IDENT, store['lhs'])) & _KEYWORDS:
            sites[STORE_FAMILY].append((start, start + len(text), store['indent']))
    return sites


def _child(source, site):
    start, end, indent = site
    text = source[start:end].strip()
    return edit(source, [(start, end, f'{indent}do {{\n{indent}    {text}\n{indent}}} while (0);')])


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for family, found in _sites(source, header, part).items():
        out += [(family, _child(source, site)) for site in found[:LIMIT]]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
