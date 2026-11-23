from decomprepair import registry
from decomprepair.last_use_double_in_place import FAMILY, variants

SOURCE = """
void unpack(u32 *out, const u32 *in) {
    u32 word;
    s32 hi;
    s32 lo;

    do {
        word = in[0];
        hi = word >> 22;
        lo = ((word * 2) & 0xFFE) - hi;
        out[0] = lo;
    } while (0);
}
"""


def test_doubles_the_value_in_place_before_its_last_use():
    [(family, revised)] = variants(SOURCE, 'unpack')
    assert family == FAMILY
    assert 'word = word * 2;\n        lo = (((word) & 0xFFE) - hi);' not in revised
    assert 'word = word * 2;' in revised and '((word) & 0xFFE)' in revised
    assert variants(revised, 'unpack') == []


def test_declines_when_the_value_is_read_afterwards():
    assert variants(SOURCE.replace('out[0] = lo;', 'out[0] = lo + word;'), 'unpack') == []


def test_declines_for_a_parameter_or_volatile():
    assert variants(SOURCE.replace('        word = in[0];\n', ''), 'unpack') == []
    assert variants(SOURCE.replace('u32 word;', 'volatile u32 word;'), 'unpack') == []


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
