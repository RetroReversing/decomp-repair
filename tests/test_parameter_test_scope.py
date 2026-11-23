"""A parameter's early flag test computed in a one-shot scope."""
import re

from decomprepair import registry
from decomprepair.parameter_test_scope import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gFlags;
extern s32 gMode;
extern void *alloc(s32 size);

void *spawn(s32 a0, s32 a1, s32 a2, s32 a3, s32 a4, s32 a5)
{
    void *obj;
    obj = alloc(0x8C);
    if (obj != 0) {
        if ((a5 << 0x18) != 0) {
            gFlags = gFlags | 0x10000000;
        } else {
            gFlags = gFlags & 0xEFFFFFFF;
        }
        gMode = a1 + a2;
        if (a3 == a4) {
            gMode = a0 - 1;
        }
        gMode = a1 * a2;
    }
    return obj;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_flag_is_computed_in_a_scope_and_tested_outside_it():
    children = [squash(text) for fam, text in variants(CODE, 'spawn')]
    assert any('do { a5_flag = a5 << 0x18; } while (0); if (a5_flag != 0) {' in text and 'int a5_flag;' in text
               for text in children)


def test_each_rarely_used_parameter_gets_its_own_proposal():
    children = [squash(text) for _, text in variants(CODE, 'spawn')]
    assert len(children) == 3  # a3 and a4 share the compare, a5 has its own
    assert any('do { a3_flag = a3 == a4; } while (0); if (a3_flag) {' in text for text in children)


def test_a_parameter_the_body_reads_often_or_never_is_left_alone():
    heavy = CODE.replace('gMode = a1 * a2;', 'gMode = a5 + a5 + a5;')
    assert all('a5_flag' not in squash(text) for _, text in variants(heavy, 'spawn'))
    assert all('a9_flag' not in squash(text) for _, text in variants(CODE.replace('s32 a5)', 's32 a9)'), 'spawn'))


def test_an_and_or_a_conditional_condition_is_left_alone():
    code = CODE.replace('(a5 << 0x18) != 0', 'a5 && gMode')
    assert all('a5_flag' not in squash(text) for _, text in variants(code, 'spawn'))
    code = CODE.replace('(a5 << 0x18) != 0', 'a5 ? gMode : 0')
    assert all('a5_flag' not in squash(text) for _, text in variants(code, 'spawn'))


def test_a_condition_that_calls_a_function_is_left_alone():
    code = CODE.replace('(a5 << 0x18) != 0', '(probe(a5) << 0x18) != 0').replace('extern s32 gMode;', 'extern s32 gMode;\nextern s32 probe(s32 a);')
    assert all('a5_flag' not in squash(text) for _, text in variants(code, 'spawn'))
    assert any('(s8)' in squash(text) for _, text in variants(CODE.replace('(a5 << 0x18) != 0', '(s8) a5 != 0'), 'spawn'))


def test_an_else_if_is_not_rewritten():
    code = CODE.replace('if ((a5 << 0x18) != 0) {', 'if (gMode) {\n            gFlags = 0;\n        } else if ((a5 << 0x18) != 0) {')
    assert all('a5_flag' not in squash(text) for _, text in variants(code, 'spawn'))


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
