"""multiply_shift_add: `(x * 0xA)` as the game's shift-and-add chain `((x << 2) + x) << 1`.

Synthetic reduction of a 30-instruction KMC N64 volume scaler (15 -> 0): a table byte times the volume times 10,
over 4096. The variant is byte-identical to the matched source's line."""
from decomprepair import multiply_shift_add as m

SOURCE = '''void f(s32 *out, u8 *row, s32 arg1) {
    out[0] = (s32) ((s32) ((*(u8 *)((s8 *)row + 2)) * (arg1 * 0xA)) / 4096);
    out[1] = (s32) ((s32) ((*(u8 *)((s8 *)row + 3)) * (arg1 * 0x64)) / 4096);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in m.variants(source, 'f') if family == m.FAMILY]


def test_a_product_by_ten_becomes_shift_add_shift():
    [text] = _texts()
    assert '* (((arg1 << 2) + arg1) << 1)) / 4096' in text
    assert 'arg1 * 0x64' in text


def test_chains_for_other_constants():
    assert m.chain('x', 3) == '((x << 1) + x)'
    assert m.chain('x', 7) == '((x << 3) - x)'
    assert m.chain('x', 14) == '(((x << 3) - x) << 1)'
    assert m.chain('x', 4) is None and m.chain('x', 11) is None and m.chain('x', 100) is None


def test_float_operand_is_left_alone():
    assert _texts('void f(f32 v, f32 *o) {\n    o[0] = (v * 10) + 1;\n}\n'.replace('(v * 10)', '(v * 0xA)')) == []


def test_it_declares_itself_to_the_registry():
    from decomprepair import registry
    assert registry.get('multiply_shift_add') is not None
