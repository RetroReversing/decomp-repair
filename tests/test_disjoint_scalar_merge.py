"""Two integer locals that are never live together, written as one variable."""
import re

from decomprepair import registry
from decomprepair.disjoint_scalar_merge import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gCount;
extern s32 gIndex;

void f(s32 *p)
{
    s32 pick, k, n, idx;

    pick = p[0];
    k = 0;
    do {
        gCount = pick + k;
        k++;
    } while (k < 4);
    idx = gIndex + 1;
    if (idx < 0) {
        idx = 0;
    }
    p[idx] = k;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def merged(code):
    return [squash(child) for family, child in variants(code, 'f') if family == FAMILY]


def test_a_local_assigned_after_the_last_use_of_another_is_renamed_to_it():
    children = merged(CODE)
    assert any('pick = p[0];' in text and 'pick = gIndex + 1;' in text and 'if (pick < 0) { pick = 0; }' in text
               and 'p[pick] = k;' in text and 'idx' not in text for text in children)
    assert any('k = 0;' in text and 'n = gIndex + 1;' not in text for text in children)


def test_the_dropped_name_leaves_the_declaration_list_valid():
    for text in merged(CODE):
        assert re.search(r's32 (?:\w+, )*\w+;', text)
        assert ', ;' not in text and ',;' not in text


def test_a_value_carried_round_a_loop_is_not_merged_into_it():
    code = CODE.replace('    idx = gIndex + 1;', '    do {\n        idx = gIndex + k;\n        gCount = idx + pick;\n    } while (idx < 2);')
    assert not any('pick = gIndex' in text for text in merged(code))


def test_a_first_reference_that_reads_the_value_is_not_merged():
    code = CODE.replace('    idx = gIndex + 1;\n    if (idx < 0) {', '    if (idx < 0) {').replace('    pick = p[0];', '    pick = p[0];\n    idx = 0;')
    assert merged(code) == [] or not any('p[pick]' in text and 'idx' not in text for text in merged(code))


def test_a_function_with_a_goto_is_left_alone():
    assert variants(CODE.replace('    p[idx] = k;', '    goto done;\ndone:\n    p[idx] = k;'), 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
