"""An unused `long long` local at the start of a block: a zero-size CLOBBER that settles a register tie (GCC 2.7.2)."""
import shutil
import subprocess

import pytest

from decomprepair import phantom_local_repairs as p

SOURCE = '''void f(s32 arg0, f32 *out) {
    s32 a;
    u32 b[2] = { 1, 2 };
    Vec3 *p = 0;

    a = arg0 + 1;
    switch (arg0 & 3) {
    case 0:
        out[0] = 1.0f;
        break;
    case 1:
    case 2:
        out[1] = 2.0f;
        break;
    default:
        break;
    }
    if (a) {
        u32 c;
        c = 2;
        out[2] = c;
    }
}
'''


def texts(source=SOURCE, **kwargs):
    return [t for _, t in p.variants(source, 'f', **kwargs)]


def lines_with(text):
    return [line for line in text.split('\n') if 'phantom_wide' in line]


def test_every_block_start_gets_one_proposal_per_signedness():
    out = texts()
    assert len(out) == 2 * 5  # the body, case 0, the stacked 1/2 labels once, default, the if body
    assert {lines_with(t)[0].strip() for t in out} == {'{ long long phantom_wide = arg0; }',
                                                       '{ unsigned long long phantom_wide = arg0; }'}
    assert all(len(lines_with(t)) == 1 for t in out)
    assert {fam for fam, _ in p.variants(SOURCE, 'f')} == {p.FAMILY}


def test_it_goes_after_the_declarations_never_among_them():
    # C89 (and gcc 2.7.2) refuse a statement before a declaration in the same block
    body = texts()[0]
    assert body.index('phantom_wide') > body.index('Vec3 *p = 0;')
    assert body.index('phantom_wide') < body.index('a = arg0 + 1;')
    inside_if = [t for t in texts() if t.index('phantom_wide') > t.index('if (a)')][0]
    assert inside_if.index('phantom_wide') > inside_if.index('u32 c;')
    assert inside_if.index('phantom_wide') < inside_if.index('c = 2;')


def test_the_switch_brace_and_initialisers_are_not_sites():
    for t in texts():
        assert 'switch (arg0 & 3) {\n    { long' not in t
        assert '{ 1, 2 {' not in t and '= { {' not in t


def test_the_block_nearest_a_line_comes_first():
    near_default = texts(near=15)[0]
    assert near_default.index('phantom_wide') > near_default.index('default:')
    assert near_default.index('phantom_wide') < near_default.index('break;', near_default.index('default:'))


def test_a_label_with_code_on_its_line_stays_on_that_line():
    out = texts('void f(s32 a) {\n    switch (a) {\n    case 0: a = 1; break;\n    default: break;\n    }\n}\n')
    assert any('case 0: { long long phantom_wide = a; } a = 1; break;' in t for t in out)


def test_a_function_that_already_has_two_is_left_alone():
    twice = SOURCE.replace('    a = arg0 + 1;', '    { long long phantom_wide = a; }\n    { long long phantom_wide2 = a; }\n    a = arg0 + 1;')
    assert p.variants(twice, 'f') == []
    once = SOURCE.replace('    a = arg0 + 1;', '    { long long phantom_wide = a; }\n    a = arg0 + 1;')
    assert all('phantom_wide2' in lines_with(t)[-1] or 'phantom_wide2' in t for _, t in p.variants(once, 'f'))


def test_a_missing_function_gives_nothing():
    assert p.variants(SOURCE, 'g') == []


@pytest.mark.skipif(shutil.which('cc') is None, reason='no host C compiler')
def test_the_program_still_does_the_same_thing(tmp_path):
    prelude = 'typedef int s32; typedef unsigned u32; typedef float f32; typedef struct { int x; } Vec3;\n'
    main = ('#include <stdio.h>\n' + 'int main(void) { float o[3]; int i, k; for (i = 0; i < 6; i++) { for (k = 0; k < 3; k++) o[k] = 0;'
            ' f(i, o); printf("%g %g %g\\n", o[0], o[1], o[2]); } return 0; }\n')

    def run(code):
        (tmp_path / 't.c').write_text(prelude + code + main)
        subprocess.run(['cc', '-w', '-o', str(tmp_path / 't'), str(tmp_path / 't.c')], check=True)
        return subprocess.run([str(tmp_path / 't')], capture_output=True, text=True, check=True).stdout

    expected = run(SOURCE)
    assert all(run(t) == expected for t in texts())
