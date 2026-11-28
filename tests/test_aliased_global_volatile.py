from decomprepair import registry
from decomprepair.aliased_global_volatile import FAMILY, variants

ALIASED = '''extern s32 D_80010000;

void wait(s32 count) {
    s32 *base;
    base = &D_80010000;
    (*base) = 0;
    while ((*(&D_80010000)) < count) {
        (*base) += 1;
    }
}
'''


def test_the_pointer_and_address_spellings_become_a_volatile_global():
    assert variants(ALIASED, 'wait') == [(FAMILY, '''extern volatile s32 D_80010000;

void wait(s32 count) {
    D_80010000 = 0;
    while ((D_80010000) < count) {
        D_80010000 += 1;
    }
}
''')]


def test_the_address_spelling_alone_is_enough():
    source = ('extern s32 G;\n\nvoid f(s32 n) {\n    G = 0;\n    while (*&G < n) {\n        G += 1;\n    }\n}\n')
    assert variants(source, 'f') == [(FAMILY, source.replace('extern s32', 'extern volatile s32').replace('*&G', 'G'))]


def test_the_parentheses_of_a_condition_stay():
    source = 'extern s32 G;\n\nvoid f(void) {\n    G = 1;\n    if (*(&G)) {\n        G = 0;\n    }\n}\n'
    assert 'if (G)' in variants(source, 'f')[0][1]


def test_an_address_used_for_anything_else_is_left_alone():
    passed = ALIASED.replace('(*base) = 0;', '(*base) = 0;\n    use(&D_80010000);')
    assert variants(passed, 'wait') == []
    walked = ALIASED.replace('(*base) += 1;', 'base[1] += 1;')
    assert variants(walked, 'wait') == []
    moved = ALIASED.replace('(*base) += 1;', 'base = other;')
    assert variants(moved, 'wait') == []


def test_a_plain_global_and_a_volatile_one_are_not_offered():
    plain = 'extern s32 G;\n\nvoid f(s32 n) {\n    G = 0;\n    while (G < n) {\n        G += 1;\n    }\n}\n'
    assert variants(plain, 'f') == []
    assert variants(ALIASED.replace('extern s32', 'extern volatile s32'), 'wait') == []


def test_it_declares_itself():
    assert registry.get('aliased_global_volatile').families == (FAMILY,)
