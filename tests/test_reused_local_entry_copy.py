from decomprepair.reused_local_entry_copy import FAMILY, PAIR, variants

SOURCE = """void act(void *arg0, s32 arg1, s32 arg2) {
    s32 (*fn)(void *);
    s32 temp_s0;
    s32 temp_s1;

    slot(arg0, arg1 & 0xFF, arg2 & 0xFF, 0);
    temp_s1 = arg1 & 0xFFFF;
    temp_s0 = temp_s1 * 16;
    fn = *(s32 (**)(void *))((u8 *)table + temp_s0);
    if (fn != NULL) {
        fn(arg0);
    }
    if ((temp_s1 == 26) & ((arg2 & 0xFFFF) == 1)) {
        return;
    }
    call(arg1 | 0x7000, temp_s0);
}
"""


def _of(family, source=SOURCE):
    return [child for kind, child in variants(source, 'act') if kind == family]


def test_the_reused_local_is_set_from_the_parameter_and_read_in_its_place_before_its_first_assignment():
    copies = _of(FAMILY)
    assert copies
    child = copies[0]
    assert 'temp_s0 = arg1;' in child
    assert 'slot(arg0, temp_s0 & 0xFF, arg2 & 0xFF, 0);' in child
    assert 'temp_s1 = temp_s0 & 0xFFFF;' in child
    assert 'call(arg1 | 0x7000, temp_s0);' in child  # the late read stays the parameter
    assert child.index('temp_s0 = arg1;') < child.index('slot(')


def test_the_copy_goes_after_a_function_pointer_declaration():
    child = _of(FAMILY)[0]
    assert child.index('s32 (*fn)(void *);') < child.index('temp_s0 = arg1;')


def test_the_pair_also_overwrites_the_other_parameter_after_its_entry_copy():
    pairs = [c for c in _of(PAIR) if 'arg2_in = 0;' in c]
    assert pairs
    child = pairs[0]
    assert 's32 arg2_in)' in child and '    s32 arg2;' in child
    assert 'temp_s0 = arg1;\n    arg2 = arg2_in;\n    arg2_in = 0;' in child
    assert 'slot(arg0, temp_s0 & 0xFF, arg2 & 0xFF, 0);' in child


def test_a_parameter_with_no_late_read_or_a_branch_before_the_assignment_is_left_alone():
    early = SOURCE.replace('call(arg1 | 0x7000, temp_s0);', 'call(temp_s1, temp_s0);')
    assert not [c for c in _of(FAMILY, early) if 'temp_s0 = arg1;' in c]
    branching = SOURCE.replace('    temp_s1 = arg1 & 0xFFFF;\n', '    if (arg1) {\n        temp_s1 = arg1 & 0xFFFF;\n    }\n')
    assert not [c for c in _of(FAMILY, branching) if 'temp_s0 = arg1;' in c]


def test_the_local_read_before_its_assignment_or_an_address_taken_parameter_gives_nothing():
    read_first = SOURCE.replace('temp_s1 = arg1 & 0xFFFF;', 'temp_s1 = temp_s0 & 0xFFFF;')
    assert not [c for c in _of(FAMILY, read_first) if 'temp_s0 = arg1;' in c]
    addressed = SOURCE.replace('fn(arg0);', 'fn(&arg1);')
    assert not [c for c in _of(FAMILY, addressed) if 'temp_s0 = arg1;' in c]


def test_it_declares_itself():
    from decomprepair import registry
    found = {repair.module for repair in registry.declared()}
    assert 'reused_local_entry_copy' in found
