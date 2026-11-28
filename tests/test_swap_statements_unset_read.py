"""The statement swap never moves a read above a local's first assignment."""
import random

import pytest

from decomprepair.permuter import _swap_statements

BODY = '''void f(s32 a) {
    s32 *p;
    s32 t;
    s32 u;
    t = a;
    p = &D;
    *p = (*p) - t;
    u = *p;
    E = u;
}'''


def swaps(source):
    out = set()
    for seed in range(200):
        lines = _swap_statements(source.split('\n'), random.Random(seed))
        out.add('\n'.join(lines) if lines else None)
    return out


def test_a_use_never_passes_its_first_assignment():
    for child in swaps(BODY) - {None}:
        assert child.index('p = &D;') < child.index('*p = (*p)')
        assert child.index('t = a;') < child.index('*p = (*p)')
        assert child.index('u = *p;') < child.index('E = u;')


def test_independent_lines_still_swap():
    assert any('    p = &D;\n    t = a;\n' in child for child in swaps(BODY) - {None})


@pytest.mark.parametrize('before', [
    '    p = &D;\n    *p = 0;\n    p = &E;\n    *p = 1;\n',   # set again: the second pair reads a value
    '    t = a;\n    D = 0;\n    t = a;\n    E = t;\n',
])
def test_a_local_set_earlier_may_move(before):
    source = f'void f(s32 a) {{\n    s32 *p;\n    s32 t;\n{before}}}'
    first, second = before.splitlines()[2:]
    assert any(f'{second}\n{first}' in child for child in swaps(source) - {None})
