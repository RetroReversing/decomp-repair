from decomprepair import doubled_division_sign as repair
from decomprepair import registry

DRAFT = '''s32 func_roll();

void func_spawn(void *arg0) {
    s32 temp_a0;
    s32 temp_hi;
    s32 temp_ret;
    s32 temp_v0;

    temp_ret = func_roll();
    temp_v0 = temp_ret;
    temp_hi = temp_ret / 3;
    temp_a0 = (temp_hi - (temp_v0 >> 0x1F)) * 3;
    (*(s16 *)((s8 *)arg0 + 0x6A)) = (s16) ((*(u16 *)((s8 *)arg0 + 0x3A)) + (temp_v0 - ((temp_hi - (temp_v0 >> 0x1F)) * 3)));
    (*(s32 *)((s8 *)arg0 + 0x1C)) = func_roll(((temp_hi - (temp_v0 >> 0x1F)) * 3), temp_hi);
}
'''


def children(source, header=''):
    return [child for _, child in repair.variants(source, 'func_spawn', header)]


def test_remainder_and_leftover_arguments_are_one_child():
    plain, dropped, trimmed = children(DRAFT)
    assert '+ (temp_v0 % 3));' in plain
    assert 'func_roll((temp_hi * 3), temp_hi)' in plain
    assert '+ (temp_v0 % 3));' in dropped and '= func_roll();\n}' in dropped
    assert 'temp_a0 = temp_hi * 3;' in dropped  # the combination that was exact keeps the unread assignments
    assert 'temp_a0 =' not in trimmed and 'temp_hi =' not in trimmed and '= func_roll();' in trimmed


def test_declared_arguments_stay():
    only = children(DRAFT, 'int func_roll(int, int);\n')
    assert all('func_roll((temp_hi * 3), temp_hi)' in child for child in only)


def test_own_prototype_loses_its_parameters():
    source = DRAFT.replace('s32 func_roll();', 's32 func_roll(s32, s32);').replace(
        '    temp_ret = func_roll();\n', '    temp_ret = other();\n')
    assert any('s32 func_roll(void);' in child for child in children(source))


def test_inline_quotient():
    source = 'void func_spawn(s32 x, s32 *out) {\n    *out = x - ((((x / 5)) - (x >> 31)) * 5);\n}\n'
    source = source.replace('(((x / 5)) - (x >> 31))', '((x / 5) - (x >> 31))')
    assert '*out = x % 5;' in children(source)[0]


def test_a_single_correction_or_a_power_of_two_is_left_alone():
    assert children('void func_spawn(s32 x, s32 *out) {\n    s32 q;\n    q = x / 3;\n    *out = x >> 31;\n}\n') == []
    assert children(DRAFT.replace('/ 3;', '/ 4;')) == []


def test_declares_itself():
    assert any(r.module == 'doubled_division_sign' for r in registry.declared())
