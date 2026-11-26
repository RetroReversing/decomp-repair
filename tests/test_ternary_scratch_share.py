"""One scratch local for a short difference and a clamp's result (an N64 strip blitter, SN GCC 2.8.1, 310 -> 0)."""
from decomprepair import registry
from decomprepair.ternary_scratch_share import FAMILY, variants

SOURCE = """extern u32 *cursor;
s32 blit(s32 x0, s32 y0, s32 x1, s32 y1, s32 texw, s32 rows)
{
    s32 h;
    s32 texh;
    s32 top;
    s32 n;
    s32 w;

    w = x1 - x0 + 1;
    h = y1 - y0;
    texh = h + 1;
    if (w < 3 || texh < 3) {
        return 0;
    }
    h = texh;
    n = rows;
    while (n > 0) {
        *cursor++ = 0x07000000 | ((((texw * n - 1) < 0x800 ? (texw * n - 1) : 0x7FF) & 0xFFF) << 12);
        n -= h;
    }
    return h;
}
"""


def children(source=SOURCE, name='blit'):
    return [text for family, text in variants(source, name, '') if family == FAMILY]


def test_the_difference_and_the_clamp_share_the_unused_local_in_one_child():
    texts = children()
    both = ('    top = y1 - y0;\n    texh = top + 1;\n' in texts[0]
            and '(((top = ((texw * n - 1) < 0x800 ? (texw * n - 1) : 0x7FF)) & 0xFFF) << 12)' in texts[0])
    assert both, texts[0]
    assert '    h = texh;\n' in texts[0] and '    s32 top;\n' in texts[0]


def test_each_edit_is_also_offered_alone():
    texts = children()
    assert any('top = y1 - y0;' in t and '(top = (' not in t for t in texts)
    assert any('top = y1 - y0;' not in t and '(top = (' in t for t in texts)


def test_a_value_read_again_later_is_not_moved():
    source = SOURCE.replace('    h = texh;\n', '    texh += h;\n')
    assert not any('top = y1 - y0;' in t for t in children(source))


def test_without_an_unused_local_a_new_scratch_is_declared():
    source = SOURCE.replace('    s32 top;\n', '')
    texts = children(source)
    assert texts and '    s32 scratch;' in texts[0] and 'scratch = y1 - y0;' in texts[0]


def test_a_whole_statement_value_is_not_a_shared_conditional():
    source = SOURCE.replace('        *cursor++ = 0x07000000 | ((((texw * n - 1) < 0x800 ? (texw * n - 1) : 0x7FF) & 0xFFF) << 12);\n',
                            '        w = (n < 0x800 ? n : 0x7FF);\n        *cursor++ = w;\n')
    assert children(source) == []


def test_registered():
    assert any(FAMILY in repair.families for repair in registry.declared())
