"""Returning cases may move only when names and behavior stay in scope."""
import shutil
import subprocess

import pytest

from decomprepair.return_case_tail import FAMILY, variants

SOURCE = '''extern int total;
void f(int state) {
    int value;
    value = 7;
    switch (state) {
    case 2:
        if (value) { total = value; }
        return;
    default:
        break;
    }
    total = 3;
}
'''


def test_case_is_outlined_inside_function_and_fallthrough_returns():
    result = variants(SOURCE, 'f')
    assert len(result) == 1 and result[0][0] == FAMILY
    child = result[0][1]
    assert 'case 2: goto __repair_return_case;' in child
    assert child.index('return;\n__repair_return_case:') < child.rfind('}')


@pytest.mark.parametrize('change,header,flags', [
    (lambda s: s.replace('return;\n    default:', 'break;\n    default:'), '', []),
    (lambda s: s.replace('if (value) { total = value; }', 'touch(); total = value;'), '', []),
    (lambda s: s.replace('if (value) { total = value; }', 'goto here; here: total = value;'), '', []),
    (lambda s: s.replace('if (value) { total = value; }\n        return;', 'if (value) return;'), '', []),
    (lambda s: s.replace('if (value) { total = value; }', 'obj.x = value;'), '', []),
    (lambda s: s.replace('if (value) { total = value; }', 'int value; value = 1; total = value;'), '', []),
    (lambda s: s.replace('int value;', 'int value; struct { int n; } item;'), '', []),
    (lambda s: s.replace('int value;', 'int (*callback)(void); int value;'), '', []),
    (lambda s: s.replace('total = 3;', 'int total; total = 3;'), '', []),
    (lambda s: s.replace('if (value) { total = value; }', 'CHANGE(value);'), '#define CHANGE(x) return', []),
    (lambda s: s, '#include_next "unknown.h"', []),
    (lambda s: s, '', ['@flags.rsp']),
])
def test_unsafe_cases_are_not_moved(change, header, flags):
    assert not variants(change(SOURCE), 'f', header, flags)


def test_inner_local_is_not_used_after_leaving_its_scope():
    source = SOURCE.replace('    int value;\n    value = 7;\n    switch', '    { int value; value = 7;\n    switch').replace('    total = 3;', '    }\n    total = 3;')
    assert not variants(source, 'f')


def test_switch_scope_shadow_is_not_moved():
    source = SOURCE.replace('switch (state) {', 'switch (state) { int value;')
    assert not variants(source, 'f')


def test_later_comma_declarator_cannot_hide_a_shadow():
    source = SOURCE.replace('switch (state) {', '{ int other, value; switch (state) {').replace('    total = 3;', '    }\n    total = 3;')
    assert not variants(source, 'f')


def test_original_and_outlined_case_agree(tmp_path):
    cc = shutil.which('cc')
    if cc is None:
        pytest.skip('a C compiler is required for the semantic control')
    child = variants(SOURCE, 'f')[0][1]
    original = SOURCE.replace('total', 'old_total').replace('void f(', 'void old_f(')
    harness = '''int total, old_total;
int main(void) {
    int i;
    for (i = -2; i < 5; ++i) {
        total = old_total = 99; f(i); old_f(i);
        if (total != old_total) return 1;
    }
    return 0;
}'''
    path = tmp_path / 'control.c'
    path.write_text(child + original + harness)
    binary = tmp_path / 'control'
    subprocess.run([cc, '-std=c89', '-Wall', '-Werror', str(path), '-o', str(binary)], check=True, timeout=30)
    subprocess.run([str(binary)], check=True, timeout=30)
