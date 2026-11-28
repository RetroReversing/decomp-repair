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


def _copy(start, *, declare='', before='', body='', other='src = base;'):
    """The copy loop with a second cursor stepped by one, started at `start`."""
    return (SOURCE.replace('    u32 i;\n', f'    u32 i;\n    s32 one;\n{declare}')
            .replace('    i = 0;\n', f'    i = 0;\n{before}')
            .replace('src = base;', f'{other}\n        one = {start};')
            .replace('put((s32 *)dst, get(src));', f'put((s32 *)dst, get(src));\n            use(one);{body}')
            .replace('src += 4;', 'src += 4;\n            one++;'))


def test_a_cursor_stepped_by_one_with_a_stable_start_is_indexed():
    assert 'use((base + i * 1));' in dict(variants(_copy('base'), 'copy'))[FAMILY]


def test_declines_a_cursor_stepped_by_one_whose_start_is_not_proven_invariant():
    for start in ('D_value', 'get(base)', '*(s32 *)base', '(s32)*ptr', 'mask ? *ptr : 0', 'base & D_value',
                  'base>D_value', '(D_value) & 3', 'base++'):
        source = _copy(start, declare='    s32 *ptr;\n')
        assert variants(source, 'copy') == [], start


def test_declines_a_start_reading_a_local_something_else_could_write():
    for declare, before, body in (('    s32 moved;\n', '', '\n            moved = 1;'),
                                  ('    s32 moved;\n', '    keep(&moved);\n', ''),
                                  ('    extern s32 moved;\n', '', ''),
                                  ('    static s32 moved;\n', '', '')):
        source = _copy('moved', declare=declare, before=before, body=body)
        assert variants(source, 'copy') == [], (declare, before, body)


def test_the_loop_rewritten_is_the_loop_checked():
    # the first loop's cursor steps by one from a global; the second loop is safe on its own
    first = ('    j = 0;\n    one = D_value;\n    if (4 != 0) {\n        do {\n            use(one);\n'
             '            j += 1;\n            one++;\n        } while (j < 4);\n    }\n')
    source = SOURCE.replace('    u32 i;\n', '    u32 i;\n    u32 j;\n    s32 one;\n').replace(
        '    i = 0;\n', first + '    i = 0;\n')
    assert variants(source, 'copy') == []


def test_declines_a_cursor_started_outside_an_outer_loop():
    # the outer loop does not restart `src`: its second pass goes on from where the first stopped
    source = SOURCE.replace('        src = base;\n', '').replace(
        '    n = size >> 2;\n', '    src = base;\n    while (more()) {\n    n = size >> 2;\n').replace(
        '    done();', '    }\n    done();')
    assert variants(source, 'copy') == []


def test_the_bound_stays_local_when_set_outside_an_outer_loop():
    source = SOURCE.replace('    i = 0;\n', '    while (more()) {\n    i = 0;\n').replace(
        '    done();', '    size = 0;\n    }\n    done();')
    assert FAMILY not in dict(variants(source, 'copy'))


def test_declines_when_the_loop_changes_the_counter_again_or_its_condition_writes_a_start():
    assert variants(SOURCE.replace('dst += 4;', 'i = next(i);\n            dst += 4;'), 'copy') == []
    assert variants(SOURCE.replace('} while (i < n);', '} while (i < n && --base);'), 'copy') == []
