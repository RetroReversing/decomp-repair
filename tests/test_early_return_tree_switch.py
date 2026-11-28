"""The early-return tree and its switch have the same observable paths."""
import shutil
import subprocess

import pytest

from decomprepair.early_return_tree_switch import FAMILY, variants

SOURCE = '''int result, flag;
void process(int input) {
    int state;
    state = input;
    if (state != 1) {
        if ((int) state >= 2) {
            if (state != 2) { return; }
            if (flag) { result = 20; }
            return;
        }
        if (state != 0) { return; }
        result = 10;
        return;
    }
    result = 30;
}
'''


def test_generate_three_cases_and_leave_continuation_after_switch():
    children = variants(SOURCE, 'process')
    assert len(children) == 1 and children[0][0] == FAMILY
    child = children[0][1]
    assert 'switch (state)' in child and all(f'case {n}:' in child for n in (0, 1, 2))
    assert child.index('result = 30;') > child.index('default:')


@pytest.mark.parametrize('change', [
    lambda s: s.replace('int state;', 'volatile int state;'),
    lambda s: s.replace('state = input;', 'state = input; { double state; state = 1; }'),
    lambda s: s.replace('state = input;', 'escape(&state); state = input;'),
    lambda s: s.replace('state != 2', 'state != 3'),
    lambda s: s.replace('state >= 2', 'state > 2'),
    lambda s: s.replace('result = 10;', 'break; result = 10;'),
    lambda s: s.replace('result = 10;', 'goto label; label: result = 10;'),
    lambda s: s.replace('result = 10;', 'typedef int T; T x; result = 10;'),
    lambda s: s.replace('result = 10;', 'struct { int x; } item; result = 10;'),
    lambda s: s.replace('if (flag) { result = 20; }', 'state = 0; if (flag) { result = 20; }'),
    lambda s: s.replace('if (flag) { result = 20; }\n            return;', 'if (flag) return;'),
    lambda s: s.replace('state = input;', 'void change(void) { state = 0; } state = input;'),
    lambda s: s.replace('result = 10;', 'MACRO; result = 10;'),
])
def test_unsafe_or_different_shapes_are_ignored(change):
    assert not variants(change(SOURCE), 'process', '#define MACRO break\n')


def test_unknown_preprocessor_input_is_not_assumed_safe():
    assert not variants(SOURCE, 'process', '#include "unknown.h"')
    assert not variants(SOURCE, 'process', flags=['-DCASE=1'])
    assert not variants(SOURCE, 'process', flags=['-include', 'x.h'])


def test_integer_alias_is_verified_before_rewriting_casts():
    source = SOURCE.replace('int state;', 's32 state;').replace('(int) state', '(s32) state')
    assert not variants(source, 'process')
    assert not variants(source, 'process', 'typedef short s32;')
    assert variants(source, 'process', 'typedef signed int s32;')


def test_original_and_child_agree_on_negative_adjacent_and_large_values(tmp_path):
    cc = shutil.which('cc')
    if cc is None:
        pytest.skip('a C compiler is required for the semantic control')
    child = variants(SOURCE, 'process')[0][1]
    original = SOURCE.replace('result, flag', 'old_result, old_flag').replace('process(', 'old_process(')
    original = original.replace('result =', 'old_result =').replace('if (flag)', 'if (old_flag)')
    harness = '''int main(void) {
        int i, f;
        for (i = -3; i <= 4; ++i) for (f = 0; f <= 1; ++f) {
            result = old_result = 99; flag = old_flag = f;
            process(i); old_process(i);
            if (result != old_result) return 1;
        }
        result = old_result = 99; process(2147483647); old_process(2147483647);
        if (result != old_result) return 1;
        result = old_result = 99; process(-2147483647 - 1); old_process(-2147483647 - 1);
        return result != old_result;
    }'''
    path = tmp_path / 'control.c'
    path.write_text(child + original + harness)
    binary = tmp_path / 'control'
    subprocess.run([cc, '-std=c89', '-Wall', '-Werror', str(path), '-o', str(binary)], check=True, timeout=30)
    subprocess.run([str(binary)], check=True, timeout=30)
