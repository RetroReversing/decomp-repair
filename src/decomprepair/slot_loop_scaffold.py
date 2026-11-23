"""A slot loop's search scaffolding written out and its addressing re-spelled, as one child.

A saved best from a long search carries a volatile table, an identity inline helper around a constant, element
addresses written pointer-first and a scaled index recomputed at each lookup. Each step is neutral or worse on its own
(`gcc-2.7.2-kmc`, a save-slot reset loop: 455 saved; the literals alone 345 but the volatile table dropped alone 540;
all four 430), so a greedy chain takes none of them. Together they are the plain loop whose register and weight rows
the next families decide (`local_weight_ladder`, `statement_scope_weight`: 430 -> 30 -> 0 on that function):

  * `pure_inline_literal`: `inline_fn(1)` is the literal `-1` the stores load into a register of their own;
  * `volatile_array_plain`: the volatile table is the plain table, stored through `lui $at; addu; sh %lo()`;
  * `pointer_index_int_form`: `&p[i]` is `(T *) (i * 2 + (s32) p)`, the scaled index first in the add;
  * `byte_index_local`: `i * 4` is held in a local set among the first insns of the body.

`variants` applies every one of those that fires on the function, in that order, and offers the result when at least
two did (`slot_loop_scaffold`); each step is also offered alone by its own module. A hypothesis; the judge decides.
"""
from . import byte_index_local, pointer_index_int_form, pure_inline_literal, volatile_array_plain_repairs

FAMILY = 'slot_loop_scaffold'
FAMILIES = (FAMILY,)


def _pick(children, preferred):
    named = [text for family, text in children if family == preferred]
    return named[0] if named else (children[0][1] if children else None)


def variants(source, name):
    text, fired = source, 0
    for module, preferred in ((pure_inline_literal, pure_inline_literal.FAMILY),
                              (volatile_array_plain_repairs, volatile_array_plain_repairs.FAMILY_ALL),
                              (pointer_index_int_form, pointer_index_int_form.FAMILY_ALL),
                              (byte_index_local, byte_index_local.FAMILY)):
        child = _pick(module.variants(text, name), preferred)
        if child and child != text:
            text, fired = child, fired + 1
    return [(FAMILY, text)] if fired >= 2 else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
