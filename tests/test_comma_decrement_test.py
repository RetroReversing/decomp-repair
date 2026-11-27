from decomprepair import comma_decrement_test as repair
from decomprepair import registry

DRAFT = '''void func_fade(void *arg0) {
    s32 temp_v0;
    s32 temp_v0_2;
    s32 var_s0;

    temp_v0 = M2C_FIELD(arg0, s32 *, 0x3C);
    temp_v0_2 = temp_v0 - 1;
    if ((temp_v0 < 0) || (M2C_FIELD(arg0, s32 *, 0x3C) = temp_v0_2, (temp_v0_2 < 0))) {
        var_s0 -= 1;
    }
}
'''


def children(source):
    return [child for _, child in repair.variants(source, 'func_fade')]


def test_the_staged_decrement_goes_back_into_the_test():
    (child,) = children(DRAFT)
    assert 'if ((M2C_FIELD(arg0, s32 *, 0x3C) < 0) || (--M2C_FIELD(arg0, s32 *, 0x3C) < 0)) {' in child
    assert 'temp_v0 =' not in child and 'temp_v0_2 =' not in child


def test_increment_and_conjunction():
    source = '''void func_fade(s32 *p, s32 *q) {
    s32 a;
    s32 b;
    a = *p;
    b = a + 1;
    if (a != 0 && (*p = b, b < 9)) {
        *q = 1;
    }
}
'''
    (child,) = children(source)
    assert 'if ((*p != 0) && (++*p < 9)) {' in child


def test_refusals():
    used_later = DRAFT.replace('var_s0 -= 1;', 'var_s0 = temp_v0;')
    other_store = DRAFT.replace('M2C_FIELD(arg0, s32 *, 0x3C) = temp_v0_2', 'M2C_FIELD(arg0, s32 *, 0x38) = temp_v0_2')
    plain_local = DRAFT.replace('temp_v0 = M2C_FIELD(arg0, s32 *, 0x3C);', 'temp_v0 = var_s0;').replace(
        'M2C_FIELD(arg0, s32 *, 0x3C) = temp_v0_2', 'var_s0 = temp_v0_2')
    for source in (used_later, other_store, plain_local):
        assert children(source) == []


def test_declared_to_the_registry():
    assert repair.FAMILY in {family for entry in registry.declared() for family in entry.families}
