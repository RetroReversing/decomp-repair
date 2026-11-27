from decomprepair import registry
from decomprepair import staged_constant_index as repairs

SOURCE = '''typedef int M2C_UNK;
extern M2C_UNK D_80001000;
extern s32 D_80002000;

void func(char *arg0) {
    s32 temp_v1;
    s32 temp_copy;

    temp_v1 = *(s32 *)(arg0 + 0x34);
    if (temp_v1 >= 0x191) {
        temp_copy = 0x190;
        *(s32 *)(arg0 + 0x34) = temp_copy;
        if ((u32) (&D_80001000)[D_80002000] < *(u8 *)(arg0 + 0x7B)) {
            *(s32 *)(arg0 + 0x3C) = -1;
        }
    } else {
        temp_copy = *(s32 *)(arg0 + 0x34);
        *(s32 *)(arg0 + 0x3C) = temp_copy;
    }
}
'''


def by_family(source):
    result = {}
    for family, text in repairs.variants(source, 'func'):
        result.setdefault(family, []).append(text)
    return result


def test_combined_child_writes_the_literal_and_the_array():
    (both,) = by_family(SOURCE)['staged_constant_array_index']
    assert '*(s32 *)(arg0 + 0x34) = 0x190;' in both and 'temp_copy = 0x190' not in both
    assert 'extern s32 D_80001000[];' in both and '(u32) D_80001000[D_80002000]' in both
    assert 's32 temp_copy;' in both  # the other arm still uses it


def test_each_half_is_offered_alone():
    children = by_family(SOURCE)
    assert '(&D_80001000)[' in children['staged_constant_inline'][0]
    assert 'temp_copy = 0x190' in children['address_index_array'][0]


def test_unused_local_loses_its_declaration():
    source = SOURCE.replace('        temp_copy = *(s32 *)(arg0 + 0x34);\n        *(s32 *)(arg0 + 0x3C) = temp_copy;\n', '')
    assert 'temp_copy' not in by_family(source)['staged_constant_inline'][0]


def test_a_later_read_that_may_see_the_constant_declines():
    source = SOURCE.replace('    } else {', '    } else {\n    }\n    if (arg0) {')
    source = source.replace('        temp_copy = *(s32 *)(arg0 + 0x34);\n', '        temp_copy += 1;\n')
    assert 'staged_constant_inline' not in by_family(source)


def test_read_in_its_own_assignment_does_not_count_as_set():
    source = SOURCE.replace('temp_copy = *(s32 *)(arg0 + 0x34);', 'temp_copy = temp_copy + 1;')
    assert 'staged_constant_inline' not in by_family(source)


def test_other_uses_of_the_symbol_keep_the_scalar():
    source = SOURCE.replace('    temp_v1 = *(s32', '    D_80001000 = 0;\n    temp_v1 = *(s32')
    assert 'address_index_array' not in by_family(source)


def test_pointer_arithmetic_on_the_address():
    source = SOURCE.replace('(&D_80001000)[D_80002000]', '*(&D_80001000 + D_80002000)')
    assert 'D_80001000[D_80002000]' in by_family(source)['address_index_array'][0]


def test_declared_in_the_registry():
    assert any(r.module == 'staged_constant_index' for r in registry.declared())
