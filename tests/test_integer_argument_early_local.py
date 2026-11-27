from decomprepair import registry
from decomprepair.integer_argument_early_local import FAMILY, REPAIR, variants

SOURCE = """void make(void *arg0) {
    s32 sum;
    void *obj;

    obj = alloc();
    obj->tag = 0xB;
    sum = arg0 + 0xD4;
    obj->slot = build(sum, &table, 0x64, 0x64, 1, 1, 0xFF, 0x46);
    finish(0x39, 0, sum);
}
"""
ASM = "addiu $t0, $zero, 0x46\nli $t1, 0xff\naddiu $a2, $zero, 0x64\n"


def kids(source=SOURCE, asm=''):
    return [c for f, c in variants(source, 'make', asm=asm) if f == FAMILY]


def test_a_stack_literal_is_held_in_a_local_set_before_the_earlier_sum():
    early = [c for c in kids() if 'k_0x46 = 0x46;\n    sum = arg0 + 0xD4;' in c]
    assert early, 'the set walks back over the unrelated sum'
    child = early[0]
    assert 's32 k_0x46;' in child
    assert '0xFF, k_0x46)' in child


def test_the_set_is_also_offered_right_above_the_call():
    assert any('k_0x46 = 0x46;\n    obj->slot = build(' in c for c in kids())


def test_the_set_never_crosses_a_brace():
    source = SOURCE.replace('    sum = arg0 + 0xD4;\n', '    if (arg0) {\n        sum = arg0 + 0xD4;\n    }\n')
    found = kids(source)
    assert found
    for child in found:
        assert 'k_0x46 = 0x46;\n        sum' not in child and 'k_0x46 = 0x46;\n    if (arg0)' not in child


def test_the_target_must_load_the_literal_when_the_assembly_is_given():
    assert kids(asm=ASM)
    assert not kids(asm='addiu $t0, $zero, 0x12\n')


def test_macros_and_trivial_literals_are_left_alone():
    source = SOURCE.replace('build(sum, &table, 0x64, 0x64, 1, 1, 0xFF, 0x46)', 'M2C_FIELD(obj, s32 *, 0x14)').replace('finish(0x39, 0, sum)', 'finish(1, 0, sum)')
    assert not kids(source)


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert registry.problems(registry.get('integer_argument_early_local')) == []


M2C = """void setup(void *arg0) {
    void *temp_s1;

    M2C_FIELD(arg0, s16 *, 0x178) = (u16) D_80094192;
    M2C_FIELD(arg0, s16 *, 0x17A) = first(D_800936DA, 0x3C, 0, 0x80, (temp_s1 = arg0 + 0xD4));
    M2C_FIELD(arg0, s16 *, 0x172) = 0x64;
    M2C_FIELD(arg0, s32 *, 0x16C) = second(temp_s1, &D_80096510, 0x64, 0x64, 1, 1, 0xC8, 0xC8, 0xC8, 0xE6, 0x47);
    M2C_FIELD(arg0, s16 *, 0x170) = 0;
}
"""


def test_a_last_stack_literal_is_set_before_the_m2c_store_that_precedes_the_call():
    # An 11-argument call in KMC 2.7.2 -O1 whose last (stack) argument is 0x47: the target loads it before the
    # `0x172` store and stores it from that register; with the literal inline the `li` is scheduled late. The set
    # one statement above the call's own, before that store, was exact (200 -> 0 on a N64 racing game's setup).
    found = [c for f, c in variants(M2C, 'setup', asm='addiu $t0, $zero, 0x47\n') if f == FAMILY]
    exact = [c for c in found if 'k_0x47 = 0x47;\n    M2C_FIELD(arg0, s16 *, 0x172) = 0x64;' in c]
    assert exact
    assert '0xE6, k_0x47)' in exact[0] and 's32 k_0x47;' in exact[0]
