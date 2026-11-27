"""A literal that two calls repeat as their stack argument is held in one local set early."""
from decomprepair import registry
from decomprepair.repeated_stack_literal_local import FAMILIES, FAMILY, REPAIR, variants

SOURCE = """void *make(void *arg0) {
    s32 sp30[3];
    void *obj;

    obj = alloc();
    obj->a = 0x14;
    obj->b = 0;
    D_X = arg0->h - 0x400;
    sp30[0] = arg0->x + 1;
    obj->c = build(sp30, &D_Y, 0x64, 0x64, 0, 1, 0xFF, 0xFF, 0xFF, 0xFF, 0x40 & 0xFF);
    sp30[0] = arg0->x - 1;
    obj->d = build(sp30, &D_Y, 0x78, 0x78, 0, 1, 0xFF, 0xFF, 0xFF, 0xFF, 0x40 & 0xFF);
    return obj;
}
"""
ASM = "addiu $s2, $zero, 0x40\nli $t1, 0xff\n"


def kids(source=SOURCE, asm=''):
    return [c for f, c in variants(source, 'make', asm=asm) if f == FAMILY]


def test_both_calls_read_the_local_and_the_mask_stays():
    found = kids()
    assert found
    for child in found:
        assert child.count('k_0x40 & 0xFF') == 2 and '0x40 & 0xFF' not in child.replace('k_0x40 & 0xFF', '')
        assert 's32 k_0x40;' in child


def test_the_set_walks_back_over_the_earlier_stores():
    assert any('k_0x40 = 0x40;\n    obj->a = 0x14;' in c for c in kids())
    assert any('k_0x40 = 0x40;\n    D_X = arg0->h' in c for c in kids())
    assert any('k_0x40 = 0x40;\n    obj->c = build(' not in c and 'k_0x40 = 0x40;\n    sp30[0] = arg0->x + 1;' in c for c in kids())


def test_the_set_never_crosses_a_brace_or_a_declaration():
    source = SOURCE.replace('    D_X = arg0->h - 0x400;\n', '    if (arg0) {\n        D_X = 1;\n    }\n')
    for child in kids(source):
        assert 'k_0x40 = 0x40;\n        D_X' not in child and 'k_0x40 = 0x40;\n    if (arg0)' not in child
    assert not any('k_0x40 = 0x40;\n    s32' in c or 'k_0x40 = 0x40;\n    void *obj' in c for c in kids())


def test_a_literal_used_by_one_call_is_left_to_the_single_call_family():
    assert not kids(SOURCE.replace('0x40 & 0xFF)', '0x41 & 0xFF)', 1))


def test_the_target_must_load_the_literal_when_the_assembly_is_given():
    assert kids(asm=ASM)
    assert not kids(asm='addiu $t0, $zero, 0x12\n')


def test_the_module_declares_itself():
    assert FAMILIES == (FAMILY,)
    assert REPAIR['families'] == FAMILIES
    assert registry.problems(registry.get('repeated_stack_literal_local')) == []
