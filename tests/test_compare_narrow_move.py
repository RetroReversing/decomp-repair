"""The narrowing moved from a callee's result to the locals it is compared with, as one child."""
import re

from decomprepair import registry
from decomprepair.compare_narrow_move import FAMILY, variants

CODE = '''typedef short s16;
typedef int s32;
typedef unsigned int u32;
volatile short magnitude(s16);
extern u32 gLimits[];

void check(s16 *p)
{
    s32 hi;
    s32 lo;
    u32 limit;
    s32 out;
    limit = gLimits[0] >> 1;
    lo = limit + 0x3000;
    hi = limit + 0x4000;
    out = 0;
    if ((hi < magnitude(p[0])) || (lo < magnitude(p[1]))) {
        out = 1;
    }
    p[2] = out;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_all_three_edits_come_as_the_first_child():
    both, kept_order = [squash(text) for _, text in variants(CODE, 'check')]
    for child in (both, kept_order):
        assert 's32 magnitude(s16);' in child
        assert 'short hi;' in child and 'short lo;' in child
        assert 'u32 limit;' in child and 's32 out;' in child
    assert 'if ((magnitude(p[0]) > hi) || (magnitude(p[1]) > lo))' in both
    assert 'if ((hi < magnitude(p[0])) || (lo < magnitude(p[1])))' in kept_order


def test_a_shared_declaration_is_split_and_a_call_already_first_stays():
    code = CODE.replace('    s32 hi;\n    s32 lo;\n', '    s32 hi, lo, other;\n').replace(
        '(hi < magnitude(p[0])) || (lo < magnitude(p[1]))', 'magnitude(p[0]) > hi || magnitude(p[1]) > lo')
    children = [squash(text) for _, text in variants(code, 'check')]
    assert len(children) == 1
    assert 's32 other; short hi, lo;' in children[0]
    assert 'if (magnitude(p[0]) > hi || magnitude(p[1]) > lo)' in children[0]


def test_nothing_for_a_wide_callee_or_a_compare_inside_arithmetic():
    assert variants(CODE.replace('volatile short magnitude', 's32 magnitude'), 'check') == []
    code = CODE.replace('(hi < magnitude(p[0])) || (lo < magnitude(p[1]))', 'limit + hi < magnitude(p[0])')
    assert variants(code, 'check') == []


def test_the_registry_runs_it():
    repair = next(r for r in registry.declared() if r.module == 'compare_narrow_move')
    assert repair.families == (FAMILY,)
