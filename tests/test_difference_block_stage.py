from decomprepair import registry
from decomprepair.difference_block_stage import FAMILY, REPAIR, variants

SOURCE = """#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK D_800AD200;
extern s32 D_800AA590;

void f(void *arg0) {
    M2C_FIELD(arg0, s32 *, 0x40) = (s32) (M2C_FIELD(&D_800AD200, s32 *, 0) + 0x11310);
    M2C_FIELD(arg0, s32 *, 0x44) = (s32) (((s32) ((M2C_FIELD(&D_800AD200, s32 *, -0x1C) - 0x11310) - M2C_FIELD(&D_800AD200, s32 *, 0)) >> 3) * 8);
    D_800AA590 = (s32) ((M2C_FIELD(&D_800AD200, s32 *, -0x1C) - 0x11310) - M2C_FIELD(&D_800AD200, s32 *, 0)) >> 3;
}
"""


def _children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_each_difference_statement_gets_its_own_block_local():
    kids = _children()
    assert len(kids) == 3  # both statements, then each alone
    both = kids[0]
    assert both.count('s32 span = M2C_FIELD(&D_800AD200, s32 *, -0x1C) - 0x11310;') == 2
    assert 'span - M2C_FIELD(&D_800AD200, s32 *, 0)' in both and '(M2C_FIELD(&D_800AD200, s32 *, -0x1C) - 0x11310)' not in both
    assert both.count('{\n') == 3  # the function's brace and one block for each statement
    assert kids[1].count('s32 span') == 1 and kids[2].count('s32 span') == 1
    assert 'M2C_FIELD(arg0, s32 *, 0x40) = (s32) (M2C_FIELD(&D_800AD200, s32 *, 0) + 0x11310);' in both  # no `- Y` after it


def test_a_local_operand_takes_its_type_and_a_used_name_gets_a_suffix():
    source = """void f(u32 a, s32 b, s32 *out) {
    s32 span;
    *out = (a - 8) - b;
}
"""
    kids = _children(source)
    assert len(kids) == 1 and 'u32 span2 = a - 8;' in kids[0] and '*out = span2 - b;' in kids[0]


def test_nothing_for_a_call_an_if_a_lone_sum_or_a_compare():
    assert _children('void f(s32 a, s32 *o) { *o = (g(a) - 8) - a; }\n') == []
    assert _children('void f(s32 a, s32 b, s32 *o) { if ((a - 8) - b) { *o = 1; } }\n') == []
    assert _children('void f(s32 a, s32 b, s32 *o) { *o = (a - 8); }\n') == []
    assert _children('void f(s32 a, s32 b, s32 *o) { *o = (a < 8) - b; }\n') == []


def test_it_is_declared_for_the_callers():
    assert registry.problems(registry.get('difference_block_stage')) == []
    assert FAMILY in REPAIR['families']
