"""Read m2c's `M2C_FIELD` fields as members of a one-member struct instead of as pointer dereferences.

GCC 2.7.2 schedules a load through `*(T *)(base + off)` below an earlier store to a scalar global, but moves
a load of `((struct { T v; } *)(base + off))->v` above it, as the original's member accesses were. On a large
N64 state machine this moved field loads to their target positions (2,327 to 2,173 differing instructions in the
machine draft, and part of the hand match that followed). The rewrite only redefines the macro the draft carries,
so every field access follows; it declines when the function uses no `M2C_FIELD`, when the draft's macro is not
the one decompdecomp writes, and when the macro is already the member form. The compiler decides: a compiler
without `__typeof__` rejects the candidate.
"""
import re

from .csource import find
from .integer_repair_support import view

FAMILY = 'field_struct_view'
SITE_FAMILY = 'field_pointer_site'
PRINTED_FAMILY = 'field_struct_view_printed'
FAMILIES = (FAMILY, SITE_FAMILY, PRINTED_FAMILY)
SITE_LIMIT = 24

POINTER_FORM = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
POINTER_SITE = '#define M2C_FIELD_PTR(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
MEMBER_FORM = ('#define M2C_FIELD(expr, type_ptr, offset) '
               '(((struct { __typeof__(*(type_ptr)0) v; } *)((s8 *)(expr) + (offset)))->v)')


_KIND = r'(s8|u8|s16|u16|s32|u32|f32|void ?\*|[A-Za-z_]\w*(?: ?\*)?)'
_OFFSET = r'(?:0x[0-9A-Fa-f]+|\d+|[A-Za-z_]\w*)'
# `*((T *) (((char *) base) + 0x10))`, the spelling m2c's printer and the saved sources carry, and the ones a cleaned
# source grows: the byte cast written `u8`, the base a symbol's address `(&sym)`, the offset a variable, or the address
# a bare `((&sym) + offset)` with no byte cast. Group 1 is the field type, 2 the address, 3 or 4 the base's name.
PRINTED = re.compile(r'\*\(\(' + _KIND + r' ?\*\) (\(\(\((?:char|u8|s8) \*\) \(?&?([A-Za-z_]\w*)\)?\) \+ ' + _OFFSET + r'\)'
                     r'|\(\(&([A-Za-z_]\w*)\) \+ ' + _OFFSET + r'\))\)')


def printed_variants(source, name):
    """The same member form for the printed spelling a saved source carries: `*((T *) (((char *) base) + off))`.

    A source a search saved has lost the `M2C_FIELD` macro, so `variants` never fires on it. Each dereference becomes
    `(((Field_T *) (((char *) base) + off))->v)` of a one-member struct typedef put before the function. On a camera
    function (KMC gcc 2.7.2) the member form on every access took the cleaned source from 8,535 to 6,105 (163 differing
    instructions; the same score as declaring the real struct), and 8,620 to 7,010 on its first saved best, while on
    the raw saved best it made it worse (8,805 to 12,336): the first scheduler's order of a load past a store to
    memory outside any struct is what changes, so this offers every access, only the stores, only the loads, and
    each base pointer's accesses alone; the judge decides."""
    if POINTER_FORM in source or MEMBER_FORM in source:
        return []
    part = view(source, name)
    if not part:
        return []
    sites = list(PRINTED.finditer(part.clean, part.opening, part.end))
    if not sites:
        return []

    def is_store(site):
        return bool(re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', part.clean[site.end():site.end() + 6]))

    def build(chosen):
        types, edits = {}, []
        for site in chosen:
            kind = site[1]
            label = 'Field_' + re.sub(r'\W', '_', kind).strip('_')
            types[label] = kind
            edits.append((site.start(), site.end(), f'((({label} *) {site[2]})->v)'))
        header = ''.join(f'typedef struct {{ {kind} v; }} {label};\n' for label, kind in sorted(types.items()))
        return edit_source(source, edits, find(source, name)[0], header)
    groups = [sites, [site for site in sites if is_store(site)], [site for site in sites if not is_store(site)]]
    groups += [[site for site in sites if (site[3] or site[4]) == base] for base in dict.fromkeys(site[3] or site[4] for site in sites)][:6]
    seen, result = set(), []
    for group in groups:
        key = tuple(site.start() for site in group)
        if group and key not in seen:
            seen.add(key)
            result.append((PRINTED_FAMILY, build(group)))
    return result


def edit_source(source, edits, definition, header):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source[:definition] + header + source[definition:]


def variants(source, name):
    if POINTER_FORM not in source:
        return []
    part = view(source, name)
    if not part or not re.search(r'\bM2C_FIELD\s*\(', part.clean[part.opening:part.end]):
        return []
    return [(FAMILY, source.replace(POINTER_FORM, MEMBER_FORM, 1))]


def site_variants(source, name, limit=SITE_LIMIT):
    """With the member form in place, put one access back to a pointer dereference.

    The member form moved the field loads of a loop into their target order, and moved a store of the same function
    one instruction too late: the original used one form for some accesses and the other for the rest. Each candidate
    switches a single `M2C_FIELD` use to `M2C_FIELD_PTR` (defined beside it), stores first."""
    if MEMBER_FORM not in source:
        return []
    if POINTER_SITE not in source:
        source = source.replace(MEMBER_FORM, MEMBER_FORM + '\n' + POINTER_SITE, 1)
    part = view(source, name)
    if not part:
        return []
    text = part.clean[part.opening:part.end]
    sites = [part.opening + m.start() for m in re.finditer(r'\bM2C_FIELD\s*\(', text)]

    def store(position):
        depth, index = 0, position + len('M2C_FIELD')
        while index < len(part.clean):
            depth += part.clean[index] == '('
            depth -= part.clean[index] == ')'
            index += 1
            if depth == 0:
                break
        return bool(re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', part.clean[index:index + 6]))
    ordered = [site for site in sites if store(site)] + [site for site in sites if not store(site)]
    return [(SITE_FAMILY, source[:site] + 'M2C_FIELD_PTR' + source[site + len('M2C_FIELD'):]) for site in ordered[:limit]]
