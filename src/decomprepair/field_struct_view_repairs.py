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
FAMILIES = (FAMILY,)

POINTER_FORM = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
MEMBER_FORM = ('#define M2C_FIELD(expr, type_ptr, offset) '
               '(((struct { __typeof__(*(type_ptr)0) v; } *)((s8 *)(expr) + (offset)))->v)')


def variants(source, name):
    if POINTER_FORM not in source:
        return []
    part = view(source, name)
    if not part or not re.search(r'\bM2C_FIELD\s*\(', part.clean[part.opening:part.end]):
        return []
    return [(FAMILY, source.replace(POINTER_FORM, MEMBER_FORM, 1))]
