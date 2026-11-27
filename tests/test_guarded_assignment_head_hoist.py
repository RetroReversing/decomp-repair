from decomprepair import registry
from decomprepair.guarded_assignment_head_hoist import FAMILY, REPAIR, variants

SOURCE = """extern s16 D_A;
extern s16 D_B;
extern s16 D_C;
extern s16 D_D;
extern s32 D_COUNT;

void f(void) {
    s32 a;
    s32 b;
    s32 c;
    s32 n;

    a = (s32) (D_A - D_B) >> 7;
    b = (s32) (D_C - D_B) >> 7;
    n = D_COUNT;
    if (n > 0) {
        c = (s32) (D_D - D_B) >> 7;
        do {
            g(a, b, c);
            n -= 1;
        } while (n > 0);
    }
}
"""


def _children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_late_sibling_joins_the_others_before_the_loads_and_the_guard():
    kids = _children()
    assert len(kids) == 1
    assert '    b = (s32) (D_C - D_B) >> 7;\n    c = (s32) (D_D - D_B) >> 7;\n    n = D_COUNT;\n    if (n > 0) {\n        do {' in kids[0]
    assert kids[0].count('c = ') == 1


def test_nothing_when_a_call_or_a_store_is_crossed_or_the_shape_has_no_sibling():
    assert _children(SOURCE.replace('n = D_COUNT;', 'n = h();')) == []
    assert _children(SOURCE.replace('n = D_COUNT;', 'D_B = 1;')) == []
    assert _children(SOURCE.replace('(s32) (D_D - D_B) >> 7', 'D_D + 3')) == []
    assert _children(SOURCE.replace('if (n > 0) {', 'while (n > 0) {')) == []
    assert _children(SOURCE.replace('        do {', '        c = 1;\n        do {')) == []  # assigned twice


def test_it_is_declared_for_the_callers():
    assert registry.problems(registry.get('guarded_assignment_head_hoist')) == []
    assert FAMILY in REPAIR['families']
