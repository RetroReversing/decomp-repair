"""A value loaded into a local only to update the place it came from, written as the compound assignment it was.

m2c writes `obj->x += (3.0f - obj->x) * 0.4f;` as `t = obj->x; obj->x = ((3.0f - t) * 0.4f) + t;`. KMC gcc 2.7.2 builds
the compound form with the field's load after the constant that is subtracted from it (`mtc1 $at, $f0` then
`lwc1 $f2, 0x34($s0)`), and the staged form with the load first, so eight rows stayed reordered in an N64 state machine
(217 instructions, -O1): 640 after the library's other repairs, 0 with all four updates written compound. Where m2c also
keeps the result for a following test (`t = obj->x; r = ((3.0f - t) * 0.4f) + t; obj->x = r; if (r > 2.8f)`), the test
reads the field again. Why gcc orders the load that way is not read in its source; the judge decides.

`split_read_modify_write` (compound_global_update_repairs) covers the three-statement form where the local is updated
once from itself; here the local is read on both sides of the operator. A site is taken only when the stored type is
written in the access (`M2C_FIELD(p, T *, off)`, `*(T *)...`) or the global's declaration and is the local's own type,
the local is used nowhere else, and neither side calls a function. All sites together come first, then each alone.
"""
import re

from .arm_block_support import IDENT, brace_pairs, statements
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'loaded_value_compound'
FAMILIES = (FAMILY,)
LIMIT = 8

SCALAR = r'(?:(?:un)?signed\s+)?(?:u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|char|short|int|long|float|double)'
TYPED = re.compile(rf'^(?:M2C_FIELD\(.+,\s*(?P<field>{SCALAR})\s*\*\s*,\s*-?\w+\)|\*\s*\(\s*(?P<deref>{SCALAR})\s*\*\s*\).+)$', re.S)


def _word(name):
    return re.compile(rf'(?<![\w.])(?<!->){re.escape(name)}\b')


def _declared(text, name):
    """The scalar type `name` is declared with, as a local or an `extern` global; None when it is not a plain scalar."""
    hit = re.search(rf'(?m)^[ \t]*(?:extern\s+|register\s+)?(?P<type>{SCALAR})\s+{re.escape(name)}\s*;', text)
    return hit['type'] if hit else None


def _pure(text):
    """No assignment, step or call (a cast and M2C_FIELD are not calls)."""
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', text):
        return False
    return not any(m[1] != 'M2C_FIELD' and m[1] not in ('sizeof',) for m in re.finditer(rf'(?<![\w.])({IDENT})\s*\(', text))


def _group(text):
    return text.startswith('(') and close(text, 0, '(', ')') == len(text)


def _split(rhs, local):
    """(operator, other side) of `other op local` / `local op other`, the other side a parenthesised group or a name."""
    word = re.escape(local)
    for pattern, ops in ((rf'^(?P<x>.+?)\s*(?P<op>[-+*|&^])\s*{word}$', '+*|&^'),
                         (rf'^{word}\s*(?P<op>[-+*|&^])\s*(?P<x>.+)$', '-+*|&^')):
        hit = re.match(pattern, rhs, re.S)
        if hit and hit['op'] in ops:
            other = hit['x'].strip()
            if _group(other) or re.fullmatch(r'[\w.]+', other):
                return hit['op'], other
    return None


def _update(rhs, local, kind):
    """The (operator, other side) of an update of `local`, with a cast to the stored type and outer parentheses read."""
    rhs = rhs.strip()
    cast = re.match(rf'^\(\s*{re.escape(kind)}\s*\)\s*', rhs)
    if cast and _group(rhs[cast.end():]):
        rhs = rhs[cast.end():]
    while _group(rhs):
        rhs = rhs[1:-1].strip()
    return _split(rhs, local)


def _assignment(text):
    hit = re.fullmatch(r'(?P<lhs>[^=;{}]+?)\s*=(?!=)\s*(?P<rhs>[^;{}]+);', text, re.S)
    return (hit['lhs'].strip(), hit['rhs'].strip()) if hit else None


def _once(source, clean, part, name, uses):
    """Whether the local `name` appears only in its declaration and the `uses` of this site."""
    found = len(_word(name).findall(clean[part.opening:part.end]))
    return found == uses + 1 and _declared(clean[part.opening:part.end], name)


def _sites(source, name):
    part = view(source, name)
    if not part:
        return part, []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return part, []
    sites = []
    for block_open, block_close in sorted(pairs.items()):
        units = statements(clean, block_open + 1, block_close)
        for index in range(len(units) - 1):
            start, end = units[index]
            load = _assignment(source[start:end].strip())
            if not load or not re.fullmatch(IDENT, load[0]):
                continue
            local, place = load
            typed = TYPED.match(place)
            kind = (typed['field'] or typed['deref']) if typed else (
                _declared(clean, place) if re.fullmatch(IDENT, place) and not _declared(clean[part.opening:part.end], place)
                else None)
            if (not kind or 'volatile' in place or not _pure(place) or _word(local).search(place)
                    or _declared(clean[part.opening:part.end], local) != kind):
                continue
            second = _assignment(source[units[index + 1][0]:units[index + 1][1]].strip())
            if not second:
                continue
            target, rhs = second
            if not _pure(rhs):
                continue
            reads = len(_word(local).findall(rhs))
            if not _once(source, clean, part, local, reads + 1):
                continue
            update = _update(rhs, local, kind)
            if not update:
                continue
            op, other = update
            value = f'({place})' if place.startswith('*') else place
            text = f'{place} {op}= {_word(local).sub(lambda _, v=value: v, other)};'
            first = (start, units[index + 1][1])
            if target == place:
                sites.append([(first[0], first[1], text)])
                continue
            # `r = ...; L = r; if (r > k)`: the result kept in a local of the same type for the test that follows
            if index + 3 >= len(units) or _declared(clean[part.opening:part.end], target) != kind:
                continue
            store_start, store_end = units[index + 2]
            if _assignment(source[store_start:store_end].strip()) != (place, target):
                continue
            test_start = units[index + 3][0]
            head = re.match(r'\s*if\s*\(', clean[test_start:])
            if not head:
                continue
            opening = test_start + head.end() - 1
            closing = close(clean, opening, '(', ')')
            if not closing:
                continue
            tests = list(_word(target).finditer(clean, opening, closing))
            if not tests or not _once(source, clean, part, target, len(tests) + 2) or not _pure(clean[opening:closing]):
                continue
            sites.append([(first[0], store_end, text)] + [(m.start(), m.end(), value) for m in tests])
    return part, sites


def variants(source, name):
    _, sites = _sites(source, name)
    if not sites:
        return []
    choices = [[e for site in sites for e in site]] + (sites if len(sites) > 1 else [])
    result, seen = [], {source}
    for edits in choices[:LIMIT]:
        text = edit(source, edits)
        if text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
