"""An increment held in a local and stored later, written `+=` in place, with the stored halfword read back."""
from decomprepair import late_store_increment as p
from decomprepair import registry

SOURCE = '''void tick(void *self)
{
    s16 height;
    s32 phase;
    s32 timer;
    s8 shade;

    timer = M2C_FIELD(self, s32 *, 0x34) + 1;
    phase = M2C_FIELD(self, s32 *, 0x3C) + 0x123;
    M2C_FIELD(self, s32 *, 0x3C) = phase;
    shade = ~(phase >> 0xC);
    M2C_FIELD(self, s32 *, 0x34) = timer;
    M2C_FIELD(self, s8 *, 0x73) = shade;
    M2C_FIELD(self, s8 *, 0x72) = shade;
    height = M2C_FIELD(self, u16 *, 0x3A) + (timer >> 2);
    M2C_FIELD(self, s16 *, 0x6A) = height;
    if ((M2C_FIELD(self, s32 *, 0x38) + 0x14) < (height & 0xFFFF)) {
        done(self);
    }
}
'''


def test_both_sums_and_the_readback_come_as_one_child():
    family, child = p.variants(SOURCE, 'tick')[0]
    assert family == p.FAMILY_READBACK
    assert 'M2C_FIELD(self, s32 *, 0x34) += 1;\n    M2C_FIELD(self, s32 *, 0x3C) += 0x123;' in child
    assert 'shade = ~(M2C_FIELD(self, s32 *, 0x3C) >> 0xC);' in child
    assert '+ (M2C_FIELD(self, s32 *, 0x34) >> 2);' in child
    assert '< ((M2C_FIELD(self, u16 *, 0x6A)))' in child
    assert 'timer' not in child and 'phase' not in child


def test_the_late_store_alone_is_offered_too():
    children = [child for family, child in p.variants(SOURCE, 'tick') if family == p.FAMILY]
    assert children
    assert all('(height & 0xFFFF)' in child for child in children)


def test_a_read_that_could_see_another_value_is_left_alone():
    store = 'M2C_FIELD(self, s32 *, 0x34) = timer;'
    for changed in (
            SOURCE.replace(store, 'other(self);\n    ' + store),
            SOURCE.replace('shade = ~(phase >> 0xC);', 'shade = M2C_FIELD(self, s32 *, 0x34);'),
            SOURCE.replace('shade = ~(phase >> 0xC);', 'shade = M2C_FIELD(peer, s32 *, 0x34);'),
            SOURCE.replace('M2C_FIELD(self, s8 *, 0x73) = shade;', 'M2C_FIELD(self, s8 *, 0x35) = shade;'),
            SOURCE.replace('done(self);', 'done(timer);')):
        assert all('M2C_FIELD(self, s32 *, 0x34) += 1;' not in child for _, child in p.variants(changed, 'tick'))


def test_it_is_declared_for_every_lane():
    assert registry.problems(registry.get('late_store_increment')) == []
