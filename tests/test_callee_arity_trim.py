"""Trailing arguments the callee's matched definition does not take (a 1300-instruction routine, 7000 -> 6935)."""
from decomprepair.callee_arity_trim import FAMILY, REPAIR, variants

SOURCE = """void tick(void *arg0, s32 idx)
{
  void *temp_a1;
  void *temp_a2;
  temp_a1 = *((void **) (((char *) arg0) + 0x68));
  speed(arg0, temp_a1);
  asset(arg0, idx, temp_a2, temp_a1);
  play(idx + 1, temp_a1);
}
"""

CALLEES = """void speed(void *actor) {
    use(actor);
}
void asset(void *actor, s32 index) {
    use(actor, index);
}
void play(s32 id, void *where) {
    use(id, where);
}
"""


def test_every_callee_together_first_then_each():
    found = [text for family, text in variants(SOURCE, 'tick', callees=CALLEES) if family == FAMILY]
    assert len(found) == 3
    assert 'speed(arg0);' in found[0] and 'asset(arg0, idx);' in found[0]
    assert 'play(idx + 1, temp_a1);' in found[0]
    assert any('speed(arg0);' in t and 'asset(arg0, idx, temp_a2, temp_a1);' in t for t in found[1:])


def test_no_callees_no_children():
    assert variants(SOURCE, 'tick') == []


def test_an_evaluated_argument_is_kept():
    source = SOURCE.replace('speed(arg0, temp_a1);', 'speed(arg0, next(temp_a1));')
    found = [text for _, text in variants(source, 'tick', callees=CALLEES)]
    assert all('speed(arg0, next(temp_a1));' in t for t in found)


def test_the_sources_prototype_loses_the_parameters_too_and_parenthesised_parameters_are_read():
    """A 182-instruction SN GCC loader: m2c's 4-parameter prototype and call of a callee defined with an array-pointer
    parameter (`s8 (*box)[4]`); the trimmed call must come with a trimmed prototype or it does not compile (120 -> 0)."""
    source = ("void draw(u8 *, s32, s32, s32);\nvoid none(s32, s32);\nvoid odd(s32, ...);\n"
              "s32 load(u8 *buf, s32 count) {\n    draw(buf, 1, 2, count);\n    none(count, count);\n    return count;\n}\n")
    callees = ("void draw(Model *m, s8 (*box)[4], Tri *tri) {\n    m->x = 1;\n}\n"
               "void none(void) {\n}\n")
    found = [text for family, text in variants(source, 'load', callees=callees) if family == FAMILY]
    assert len(found) == 3
    both = found[0]
    assert 'void draw(u8 *, s32, s32);' in both and 'draw(buf, 1, 2);' in both
    assert 'void none(void);' in both and 'none();' in both
    assert 'void odd(s32, ...);' in both
    assert any('void draw(u8 *, s32, s32);' in t and 'void none(s32, s32);' in t for t in found[1:])


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and 'callees' in REPAIR['needs']
