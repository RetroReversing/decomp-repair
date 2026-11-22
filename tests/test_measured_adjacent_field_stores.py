from decomprepair import measured_adjacent_field_stores as repair

HEADER = 'typedef signed char s8; typedef signed short s16; typedef signed int s32;'
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void f(void *obj, s32 value) {
    M2C_FIELD(obj, s32 *, 12) = value;
    M2C_FIELD(obj, s16 *, 8) = 14;
}
'''
ROWS = [('o', 'sh $v0, 8($a2)', 'sw $s2, 12($a2)'),
        ('o', 'sw $s2, 12($a2)', 'sh $v0, 8($a2)')]


def test_reorders_adjacent_disjoint_stores_when_target_requires_it():
    (_, candidate), = repair.variants(SOURCE, 'f', HEADER, ROWS)
    assert candidate.index('s16 *, 8') < candidate.index('s32 *, 12')


def test_rejects_aliases_side_effects_and_unrelated_evidence():
    assert not repair.variants(SOURCE, 'f', HEADER, ROWS[:1])
    assert not repair.variants(SOURCE.replace('s16 *, 8', 's16 *, 13'), 'f', HEADER,
                               [('o', 'sh $v0, 13($a2)', 'sw $s2, 12($a2)'),
                                ('o', 'sw $s2, 12($a2)', 'sh $v0, 13($a2)')])
    assert not repair.variants(SOURCE.replace(' = value;', ' = load();'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE.replace('void *obj', 'volatile void *obj'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE.replace('    M2C_FIELD(obj, s32', '    take(&obj);\n    M2C_FIELD(obj, s32'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE.replace('    M2C_FIELD(obj, s32', '    take(&value);\n    M2C_FIELD(obj, s32'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE, 'f', HEADER + '\n#define value hidden', ROWS)
