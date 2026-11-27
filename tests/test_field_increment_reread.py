"""A place incremented through a temporary that is read again, written as `+=` with the later reads re-reading it."""
from decomprepair import field_increment_reread as p
from decomprepair import registry

SOURCE = '''void tick(void *self)
{
    s32 sum;

    sum = M2C_FIELD(self, s32 *, 0x34) + 1;
    M2C_FIELD(self, s32 *, 0x34) = sum;
    M2C_FIELD(self, s32 *, 0x3C) = (s32) (M2C_FIELD(self, s32 *, 0x3C) + 0x123);
    M2C_FIELD(self, u16 *, 0x6A) = M2C_FIELD(self, u16 *, 0x3A) + (sum >> 2);
    done(self);
}
'''


def test_the_increment_and_the_later_read():
    [(family, child)] = p.variants(SOURCE, 'tick')
    assert family == p.FAMILY
    assert 'M2C_FIELD(self, s32 *, 0x34) += 1;' in child
    assert '+ (M2C_FIELD(self, s32 *, 0x34) >> 2);' in child
    assert 'sum' not in child


def test_a_member_and_a_global():
    member = '''void tick(struct t *self)
{
    s32 sum;
    sum = self->timer - 2;
    self->timer = sum;
    self->frame = sum;
}
'''
    assert 'self->timer -= 2;' in p.variants(member, 'tick')[0][1]
    assert 'self->frame = self->timer;' in p.variants(member, 'tick')[0][1]
    plain = member.replace('self->timer', 'gTimer').replace('self->frame', 'gFrame')
    assert 'gTimer -= 2;' in p.variants(plain, 'tick')[0][1]


def test_a_read_that_could_see_another_value_is_left_alone():
    for changed in (
            SOURCE.replace('M2C_FIELD(self, s32 *, 0x3C) = (s32)', 'other(self);\n    M2C_FIELD(self, s32 *, 0x3C) = (s32)'),
            SOURCE.replace('M2C_FIELD(self, s32 *, 0x3C) = (s32)', 'M2C_FIELD(peer, s32 *, 0x3C) = (s32)'),
            SOURCE.replace('M2C_FIELD(self, s32 *, 0x3C) = (s32) (M2C_FIELD(self, s32 *, 0x3C) + 0x123);',
                           'M2C_FIELD(self, s32 *, 0x34) = 0;'),
            SOURCE.replace('done(self);', 'done(sum);'),
            SOURCE.replace('s32 *, 0x34', 'u16 *, 0x34')):
        assert p.variants(changed, 'tick') == []


def test_it_is_declared_for_every_lane():
    assert registry.problems(registry.get('field_increment_reread')) == []
