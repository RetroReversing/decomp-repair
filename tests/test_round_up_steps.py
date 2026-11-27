"""A round-up written back into its own variable as three statements."""
from decomprepair import round_up_steps as steps

SOURCE = '''void f(u32 size, s32 n) {
    size = ((u32) (size + 0xF) >> 4) * 0x10;
    n = (((u32)(n) + 0xF) >> 4) << 4;
    send(size, n);
}
'''


def test_each_site_and_all_sites():
    out = [text for _, text in steps.variants(SOURCE, 'f')]
    assert len(out) == 3
    assert '    size += 0xF;\n    size >>= 4;\n    size <<= 4;\n' in out[0]
    assert '    n += 0xF;\n    n = (u32) n >> 4;\n    n <<= 4;\n' in out[0]
    assert 'n = (((u32)(n) + 0xF) >> 4) << 4;' in out[1]


def test_another_variable_or_a_mismatched_scale_is_left_alone():
    other = SOURCE.replace('size = ((u32) (size', 'size = ((u32) (n').replace('<< 4;\n    send', '<< 3;\n    send')
    assert steps.variants(other, 'f') == []
