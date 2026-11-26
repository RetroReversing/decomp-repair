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
