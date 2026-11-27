from decomprepair.integer_cursor_for_loop import BOUND_LOCAL, FAMILY, variants
from decomprepair.stepped_induction_index import variants as stepped

SOURCE = """
void copy(u32 mask) {
    s32 base;
    u32 size;
    u32 n;
    u32 i;
    s32 src;
    s32 dst;

    base = get(0x10) & mask;
    size = get(0x14);
    n = size >> 2;
    i = 0;
    if (n != 0) {
        n = n;
        dst = base & 0xB07FFFFF;
        src = base;
        do {
            put((s32 *)dst, get(src));
            dst += 4;
            i += 1;
            src += 4;
        } while (i < n);
    }
    done();
}
"""


def test_cursors_for_loop_and_bound_are_one_child():
    result = dict(variants(SOURCE, 'copy'))
    text = result[FAMILY]
    assert 'for (i = 0; i < (size >> 2); i += 1) {' in text
    assert 'put((s32 *)((base & 0xB07FFFFF) + i * 4), get((base + i * 4)));' in text
    assert 'dst +=' not in text and 'src +=' not in text and 'n = ' not in text
    assert 'for (i = 0; i < n; i += 1) {' in result[BOUND_LOCAL] and 'n = size >> 2;' in result[BOUND_LOCAL]
    assert variants(text, 'copy') == []


def test_a_start_that_binds_looser_than_addition_is_parenthesized():
    # `p = a & MASK;` stepped by 4 is `(a & MASK) + i * 4`, not `a & (MASK + i * 4)`
    assert '((base & 0xB07FFFFF) + i * 4)' in stepped(SOURCE, 'copy')[0][1]


def test_declines_a_start_the_loop_could_change_or_that_reads_memory_or_calls():
    for start in ('get(base)', '*(s32 *)base', 'D_value', 'moved'):
        source = SOURCE.replace('src = base;', f'src = {start};').replace(
            'dst = base & 0xB07FFFFF;', f'dst = {start};').replace('done();', 'moved = 1;\n    done();')
        if start == 'moved':
            source = source.replace('    u32 i;\n', '    u32 i;\n    s32 moved;\n').replace(
                'put((s32 *)dst, get(src));', 'put((s32 *)dst, get(src));\n            moved++;')
        assert variants(source, 'copy') == [], start


def test_the_bound_stays_local_when_it_is_read_again():
    result = dict(variants(SOURCE.replace('done();', 'done(n);'), 'copy'))
    assert FAMILY not in result and BOUND_LOCAL in result
