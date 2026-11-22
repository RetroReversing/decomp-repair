"""The statements that open a function wrapped in a `do { } while (0)`, a barrier for the first scheduler.

Synthetic shape of the 851-instruction ray test's head: parameters spilled across calls, a float copy and a record's
components computed from two pointer parameters, a narrow flag passed on the stack."""
from decomprepair import entry_scheduling_scope as e

SOURCE = '''s32 cast(s32 (*cb)(f32 *), void **list, f32 *start, f32 *dir, void *out, f32 span, void *plane, u8 flag, void *skip)
{
    struct {
        f32 x;
        f32 y;
    } end;
    f32 dist;
    void **cursor;
    dist = span;
    end.x = *start + (*dir * dist);
    end.y = start[1] + (dir[1] * dist);
    cursor = list;
    if (cursor != 0) {
        do {
            if (flag != 0) {
                dist = cb(start) & 0xFF;
            }
            cursor = *cursor;
        } while (cursor != 0);
    }
    return dist < span;
}
'''


def _texts(source=SOURCE):
    found = e.variants(source, 'cast')
    assert all(family == e.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_leading_run_is_wrapped():
    wrapped = _texts()[0]
    assert '    do {\n    dist = span;\n    end.x = *start + (*dir * dist);\n    end.y = start[1] + (dir[1] * dist);\n    cursor = list;\n    } while (0);\n    if (cursor != 0) {' in wrapped
    assert wrapped.index('f32 dist;') < wrapped.index('do {')


def test_a_narrow_stack_parameter_is_read_through_a_local_set_first_in_the_run():
    wrapped = _texts()[0]
    copied = next(t for t in _texts() if '        copy_flag = flag;\n    dist = span;' in t and 'staged_' not in t)
    assert 'copy_flag' not in wrapped
    assert '    do {\n        copy_flag = flag;\n    dist = span;' in copied
    assert 'if (copy_flag != 0) {' in copied
    assert copied.index('u8 copy_flag;') < copied.index('f32 dist;')


def test_the_run_must_have_three_plain_statements():
    short = SOURCE.replace('    end.y = start[1] + (dir[1] * dist);\n    cursor = list;\n', '')
    assert _texts(short) == []


def test_a_call_in_the_run_ends_it():
    called = SOURCE.replace('    cursor = list;\n', '    cursor = pick(list);\n    end.y = 0;\n')
    wrapped = _texts(called)[0]
    assert 'pick(list)' in wrapped.split('} while (0);')[1]


def test_a_function_that_already_has_the_wrapper_is_left_alone():
    assert _texts(SOURCE.replace('    dist = span;', '    do { dist = span; } while (0);')) == []


def test_the_first_product_dereference_is_staged_first_in_the_run():
    texts = _texts(SOURCE.replace('f32 dist;', 'f32 dist;\n    f32 tmp;').replace('end.x = *start + (*dir * dist);', 'end.x = *start + (*dir * dist);'))
    staged = [t for t in texts if 'staged_dir = *dir;' in t]
    assert staged
    assert 'end.x = *start + (staged_dir * dist);' in staged[0]
    assert staged[0].index('staged_dir = *dir;') < staged[0].index('dist = span;')
