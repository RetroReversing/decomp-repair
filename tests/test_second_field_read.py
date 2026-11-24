"""second_field_read: a field read once into a local and used twice, read again after an intervening store."""
from decomprepair import registry
from decomprepair import second_field_read as sfr

NAME = 'func_80012340'
SOURCE = '''void func_80012340(void *arg0) {
    s32 temp_a;
    s32 temp_t;

    temp_a = M2C_FIELD(arg0, s32 *, 0x7C);
    temp_t = M2C_FIELD(arg0, s32 *, 0x80);
    M2C_FIELD(arg0, s32 *, 0x7C) = temp_a + 1;
    M2C_FIELD(arg0, s32 *, 0x64) = temp_t;
    M2C_FIELD(arg0, s32 *, 0x80) = temp_t - 5;
}
'''
ASM = '''
glabel func_80012340
    /* 0 */  lw         $a1, 0x7C($a0)
    /* 4 */  lw         $a2, 0x80($a0)
    /* 8 */  addiu      $a3, $a1, 0x1
    /* c */  sw         $a3, 0x7C($a0)
    /* 10 */  lw        $v0, 0x80($a0)
    /* 14 */  addu      $v1, $v0, $zero
    /* 18 */  addiu     $v0, $v0, -0x5
    /* 1c */  sw        $a2, 0x64($a0)
    /* 20 */  jr        $ra
    /* 24 */   sw       $v0, 0x80($a0)
endlabel func_80012340
'''


def _children(source=SOURCE, asm=ASM, **kw):
    return sfr.variants(source, NAME, asm=asm, **kw)


def test_the_target_copy_of_a_just_loaded_field_is_the_gate():
    assert sfr.evidence(ASM) == {0x80}
    plain = ASM.replace('addu      $v1, $v0, $zero', 'nop')
    assert sfr.evidence(plain) == set() and _children(asm=plain) == [] and _children(asm='') == []
    assert sfr.evidence(ASM.replace('addu      $v1, $v0, $zero', 'move $v1, $v0')) == {0x80}
    other = ASM.replace('0x80($a0)\n    /* 14 */', '0x84($a0)\n    /* 14 */')
    assert sfr.evidence(other) == {0x84} and _children(asm=other) == []  # (a copy of another field: not this one)


def test_the_second_use_reads_the_field_again_after_the_intervening_store():
    family, text = next(c for c in _children() if c[0] == sfr.FAMILY)
    assert 'temp_t_2;' in text.split('temp_a = ')[0]
    after = text.split('M2C_FIELD(arg0, s32 *, 0x7C) = temp_a + 1;\n')[1]
    assert after.startswith('    temp_t_2 = M2C_FIELD(arg0, s32 *, 0x80);\n')
    assert 'M2C_FIELD(arg0, s32 *, 0x64) = temp_t_2;' in text or 'M2C_FIELD(arg0, s32 *, 0x80) = temp_t_2 - 5;' in text


def test_one_child_per_use_and_a_late_form():
    families = [c[0] for c in _children()]
    assert families.count(sfr.FAMILY) == 2 and families.count(sfr.LATE_FAMILY) == 1
    texts = [t for f, t in _children() if f == sfr.FAMILY]
    assert any('0x64) = temp_t_2;' in t for t in texts) and any('0x80) = temp_t_2 - 5;' in t for t in texts)
    late = next(t for f, t in _children() if f == sfr.LATE_FAMILY)
    assert late.count('temp_t_2 = M2C_FIELD(arg0, s32 *, 0x80);') == 1 and 'temp_t_2 = M2C_FIELD(arg0, s32 *, 0x80);\n    M2C_FIELD(arg0, s32 *, 0x80) = temp_t_2 - 5;' in late


def test_declines_what_could_change_the_field_or_is_not_the_shape():
    alias = SOURCE.replace('M2C_FIELD(arg0, s32 *, 0x7C) = temp_a + 1;', 'M2C_FIELD(arg1, s32 *, 0x7C) = temp_a + 1;')
    assert _children(alias) == []  # (another pointer may alias the field)
    overlap = SOURCE.replace('0x7C) = temp_a + 1;', '0x7E) = temp_a + 1;').replace('s32 *, 0x7E', 's16 *, 0x7E').replace('s32 *, 0x80', 's32 *, 0x80')
    assert _children(overlap)  # (0x7E..0x80 does not reach 0x80: still the shape)
    clobber = SOURCE.replace('0x7C) = temp_a + 1;', '0x80) = temp_a + 1;')
    assert _children(clobber) == []  # (the intervening store is to the field itself)
    called = SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x7C) = temp_a + 1;\n', '    foo(arg0);\n    M2C_FIELD(arg0, s32 *, 0x7C) = temp_a + 1;\n')
    assert _children(called) == []
    single = SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x64) = temp_t;\n', '')
    assert _children(single) == []  # (one use: nothing to split)


def test_a_loop_or_branch_naming_the_local_is_left_alone():
    looped = SOURCE.replace('}\n', '    while (temp_t) {\n        temp_t -= 1;\n    }\n}\n')
    assert _children(looped) == []


def test_registered_for_every_lane_and_needs_the_assembly():
    found = {r.module: r for r in registry.declared()}['second_field_read']
    assert set(found.families) == set(sfr.FAMILIES) and 'asm' in found.needs and found.archs == ('mips',)
