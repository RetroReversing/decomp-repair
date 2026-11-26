"""base_sum_local: two sums of one base with different addends held in one local, set before each use.

Synthetic shape of a 398-instruction SN64 GCC 2.8.1 glyph printer (4122 -> 4122 -> 3847 with temporary_hoist after):
the target keeps `x4 + step` and the accent's `x4 + 64` in the dead parameter's saved register."""
from decomprepair import base_sum_local as s

SOURCE = '''void glyph(s32 c, s32 first) {
    s32 idx;
    s32 x4;
    s32 step;
    s32 spare;

    idx = c - 0x20;
    if (first) {
        reset();
    }
    step = 64 / gScale;
    x4 = gX * 4;
    rect(((x4 + step) & 0xFFF) << 12, x4 & 0xFFF);
    if (idx >= 0xA0) {
        tex(idx);
        rect(((x4 + 64) & 0xFFF) << 12, x4 & 0xFFF);
    }
    gX += step;
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'glyph') if family == s.FAMILY]


def test_a_new_local_a_dead_local_and_the_dead_parameter():
    texts = _texts()
    held = {t.split(' = x4 + step;')[0].split('\n')[-1].strip() for t in texts}
    assert held == {'sum', 'spare', 'c', 'first'}
    new = next(t for t in texts if 'sum = x4 + step;' in t and 'if (idx >= 0xA0) {\n        sum = x4 + 64;' in t)
    assert '    s32 sum;\n' in new
    assert '    sum = x4 + step;\n    rect((sum & 0xFFF) << 12, x4 & 0xFFF);' in new
    assert '        rect((sum & 0xFFF) << 12, x4 & 0xFFF);' in new
    param = next(t for t in texts if 'c = x4 + step;' in t and '        tex(idx);\n        c = x4 + 64;' in t)
    assert 's32 c;' not in param


def test_live_locals_and_late_parameters_are_not_used():
    live = SOURCE.replace('    gX += step;', '    gX += step + spare;')
    assert not any('spare = x4' in t for t in _texts(live))
    late = SOURCE.replace('        tex(idx);', '        tex(c);')
    assert not any('c = x4' in t for t in _texts(late))


def test_one_sum_or_the_same_addend_declines():
    assert _texts(SOURCE.replace('(x4 + 64)', '(x4 + step)')) == []
    assert _texts(SOURCE.replace('(x4 + 64)', '(x4 * 64)')) == []


def test_a_later_sum_outside_a_nested_block_declines():
    flat = SOURCE.replace('    if (idx >= 0xA0) {\n        tex(idx);\n        rect(((x4 + 64) & 0xFFF) << 12, x4 & 0xFFF);\n    }\n',
                          '    rect(((x4 + 64) & 0xFFF) << 12, x4 & 0xFFF);\n')
    assert _texts(flat) == []


POINTER = '''void tile(s32 c, u8 ch) {
    u8 *font;
    u8 *spare;
    s32 idx;

    font = gFont;
    idx = c - 0x20;
    load((u32)(font + idx * 0xD0) & ~7);
    if (ch >= 0xC0) {
        mark(ch);
        load((u32)(font + (gAccent[ch - 0xC0] - 0x20) * 0xD0) & ~7);
    }
}
'''


def test_a_pointer_base_takes_a_local_of_its_type_and_any_pure_addend():
    texts = [text for family, text in s.variants(POINTER, 'tile') if family == s.FAMILY]
    new = next(t for t in texts if 'u8 *sum;' in t and '    mark(ch);\n        sum = font' in t)
    assert '    sum = font + idx * 0xD0;\n    load((u32)sum & ~7);' in new
    assert '        sum = font + (gAccent[ch - 0xC0] - 0x20) * 0xD0;\n        load((u32)sum & ~7);' in new
    assert any('spare = font + idx * 0xD0;' in t for t in texts)
    assert not any('c = font' in t or 'idx = font' in t for t in texts)  # integers do not hold a pointer
    called = POINTER.replace('(gAccent[ch - 0xC0] - 0x20)', 'pick(ch)')
    assert not [t for f, t in s.variants(called, 'tile') if f == s.FAMILY]
