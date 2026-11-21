"""Per-case temporaries of one switch: split a shared local into a local per case, or merge locals that never meet."""
import shutil
import subprocess

import pytest

from decomprepair import case_temporary_repairs as c

SOURCE = '''void f(s32 arg0, s32 *out) {
    u32 a;
    u32 b;
    u32 c;
    s32 k;

    k = arg0;
    switch (arg0 & 3) {
    case 0:
        a = k + 1;
        out[0] = a;
        break;
    case 1:
        a = k + 2;
        c = a * 2;
        out[1] = c;
        break;
    case 2:
        b = k + 3;
        out[2] = b;
        break;
    default:
        c = 0;
        out[3] = c;
        break;
    }
}
'''


def of(family, source=SOURCE):
    return [t for fam, t in c.variants(source, 'f') if fam == family]


def test_a_local_shared_by_two_cases_is_split_in_both_or_in_one():
    out = of(c.SPLIT)
    both = [t for t in out if '    u32 a_0;\n    u32 a_1;\n' in t][0]
    assert 'a_0 = k + 1;' in both and 'a_1 = k + 2;' in both and '    u32 a;\n' not in both
    one = [t for t in out if 'u32 a_1;' in t and 'u32 a;' in t][0]
    assert 'a = k + 1;' in one and 'a_1 = k + 2;' in one and 'a_0' not in one


def test_the_default_case_is_named_by_its_label():
    assert any('c_default' in t and 'c_1' in t for t in of(c.SPLIT))


def test_locals_of_one_type_that_never_meet_are_merged():
    merged = [t for t in of(c.MERGE) if '    u32 b;\n' not in t and 'u32 a;' in t]
    assert merged and 'a = k + 3;' in merged[0] and 'out[2] = a;' in merged[0]


def test_locals_that_share_a_case_are_not_merged():
    # a and c are both used in case 1
    assert not any('u32 c;' not in t and 'c = a * 2' not in t and 'a = a * 2' in t for t in of(c.MERGE))
    assert all('a = a * 2' not in t and 'c = c * 2' not in t for t in of(c.MERGE))


def test_other_types_are_never_merged():
    typed = SOURCE.replace('    u32 b;', '    s32 b;')
    assert not any('b' not in t.split('{')[0] and 'a = k + 3' in t for t in of(c.MERGE, typed))


@pytest.mark.parametrize('edit', [
    lambda s: s.replace('    k = arg0;\n', '    k = arg0;\n    a = 0;\n'),  # used outside the switch
    lambda s: s.replace('        a = k + 2;\n', '        c = a + 2;\n        a = k + 2;\n'),  # read before written in a case
    lambda s: s.replace('        a = k + 2;\n', '        a += k + 2;\n'),  # a compound assignment is a read first
    lambda s: s.replace('        a = k + 2;\n', '        a = a + 2;\n'),  # the right side reads it
    lambda s: s.replace('        a = k + 2;\n', '        if (k) {\n            a = k + 2;\n        }\n        c = a;\n'),  # written only on one path
    lambda s: s.replace('out[0] = a;', 'g(&a);'),  # address taken
])
def test_a_local_with_a_value_crossing_cases_is_left_alone(edit):
    out = c.variants(edit(SOURCE), 'f')
    assert not any('a_0' in t or 'a_1' in t for _, t in out)
    assert not any(fam == c.MERGE and 'a = k + 3' in t for fam, t in out)


def test_a_label_inside_the_switch_or_a_nested_case_label_leaves_it_alone():
    assert c.variants(SOURCE.replace('        out[2] = b;', 'again:\n        out[2] = b;'), 'f') == []
    nested = SOURCE.replace('        out[2] = b;\n', '        if (k) {\n    case 7:\n            out[2] = b;\n        }\n')
    assert c.variants(nested, 'f') == []


def test_declarations_with_initialisers_or_arrays_are_not_touched():
    source = SOURCE.replace('    u32 a;', '    u32 a = 0;')
    assert not any('a_0' in t for _, t in c.variants(source, 'f'))


def test_a_name_already_taken_is_not_reused():
    source = SOURCE.replace('    u32 c;', '    u32 c;\n    u32 a_0;')
    assert all(t.count('u32 a_0;') == 1 or 'a_0_' in t for fam, t in c.variants(source, 'f') if fam == c.SPLIT)


def test_nothing_without_a_switch_or_function():
    assert c.variants('void f(void) {\n    u32 a;\n    a = 1;\n}\n', 'f') == []
    assert c.variants(SOURCE, 'g') == []


@pytest.mark.skipif(shutil.which('cc') is None, reason='no host C compiler')
def test_every_proposal_computes_the_same_values(tmp_path):
    prelude = 'typedef int s32; typedef unsigned u32;\n'
    main = ('#include <stdio.h>\nint main(void) { int o[4], i, j; for (i = 0; i < 8; i++) { for (j = 0; j < 4; j++) o[j] = -1;'
            ' f(i, o); printf("%d %d %d %d\\n", o[0], o[1], o[2], o[3]); } return 0; }\n')

    def run(code):
        (tmp_path / 't.c').write_text(prelude + code + main)
        subprocess.run(['cc', '-w', '-o', str(tmp_path / 't'), str(tmp_path / 't.c')], check=True)
        return subprocess.run([str(tmp_path / 't')], capture_output=True, text=True, check=True).stdout

    expected = run(SOURCE)
    proposals = c.variants(SOURCE, 'f')
    assert len(proposals) >= 6
    assert all(run(t) == expected for _, t in proposals)
