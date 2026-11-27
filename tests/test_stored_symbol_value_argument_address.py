"""A global stored with a constant and passed as `SYM + K` is passed by address."""
from decomprepair import registry
from decomprepair.stored_symbol_value_argument_address import FAMILIES, FAMILY, REPAIR, variants

SOURCE = """extern s8 D_800BBBA8;
extern s8 D_800BBC00[];
void setup(s32 a) {
    D_800BBBA8 = 0;
    show(D_800BBBA8 + 1, 2, 0xF, 0, 0x140, 0, 1);
    show(D_800BBC00 + 1, 2);
}
"""


def kids(source=SOURCE):
    return [c for f, c in variants(source, 'setup') if f == FAMILY]


def test_the_stored_global_is_passed_by_address():
    found = kids()
    assert len(found) == 1
    assert 'show(&D_800BBBA8 + 1, 2, 0xF' in found[0] and 'show(D_800BBC00 + 1, 2)' in found[0]


def test_needs_the_store_before_the_call_and_a_scalar_global():
    assert not kids(SOURCE.replace('    D_800BBBA8 = 0;\n', ''))
    assert not kids(SOURCE.replace('extern s8 D_800BBBA8;', 'extern s8 D_800BBBA8[];'))
    assert not kids(SOURCE.replace('D_800BBBA8 + 1', 'a + 1'))


def test_the_module_declares_itself():
    assert FAMILIES == (FAMILY,)
    assert REPAIR['families'] == FAMILIES
    assert registry.problems(registry.get('stored_symbol_value_argument_address')) == []
