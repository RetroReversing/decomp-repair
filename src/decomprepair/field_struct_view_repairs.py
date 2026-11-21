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

from .integer_repair_support import view

FAMILY = 'field_struct_view'
SITE_FAMILY = 'field_pointer_site'
FAMILIES = (FAMILY, SITE_FAMILY)
SITE_LIMIT = 24

POINTER_FORM = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
POINTER_SITE = '#define M2C_FIELD_PTR(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
MEMBER_FORM = ('#define M2C_FIELD(expr, type_ptr, offset) '
               '(((struct { __typeof__(*(type_ptr)0) v; } *)((s8 *)(expr) + (offset)))->v)')


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
