from decomprepair import registry
from decomprepair import split_multiple_rejoin as module

# a record pick: the target built `&records[channel]` in stages across the branches before the join
DRAFT = """extern u8 flags;
extern u8 records;
void pick(s32 arg0) {
    u8 *__base_flags;
    s32 two;
    s32 three;
    s32 channel;
    void *record;

    channel = arg0;
    if (channel == 1) {
        two = channel * 2;
        __base_flags = &flags;
        if (__base_flags[1] == 0) {
            if (__base_flags[2] == channel) {
                channel = 2;
                goto block_10;
            }
        }
        goto block_11;
    }
    two = channel * 2;
    if (channel == 2) {
        three = channel * 3;
        if (__base_flags[2] == 0) {
            if (__base_flags[3] == 1) {
                channel = 3;
            }
block_10:
            two = channel * 2;
            goto block_11;
        }
    } else {
block_11:
        three = two + channel;
    }
    record = (void *)((((three * 4) + channel) * 8));
    use(record);
}
"""


def children(source=DRAFT):
    return dict((family, text) for family, text in reversed(module.variants(source, 'pick')))


def test_staged_multiples_become_one_multiply():
    child = children()[module.FAMILY]
    assert 'two' not in child and 'three' not in child
    assert 'record = (void *)(channel * 0x68);' in child.replace('((channel * 0x68))', '(channel * 0x68)')
    assert 'block_11:\n;' in child


def test_base_is_set_again_in_the_arm_its_assignment_does_not_reach():
    child = children()[module.BASE_FAMILY]
    arm = child.index('if (channel == 2) {')
    assert child[arm:].split('\n')[1].strip() == '__base_flags = &flags;'
    assert child.count('__base_flags = &flags;') == 2


def test_both_are_offered_as_one_first_child():
    family, child = module.variants(DRAFT, 'pick')[0]
    assert family == module.BOTH_FAMILY
    assert 'three' not in child and child.count('__base_flags = &flags;') == 2
    assert module.variants(child, 'pick') == []


def test_a_multiple_read_after_the_value_changed_is_kept():
    source = """void pick(s32 i) {
    s32 four;

    four = i * 4;
    i = i + 1;
    use(four, i);
}
"""
    assert module.variants(source, 'pick') == []


def test_a_multiple_set_on_one_path_only_is_kept():
    source = """void pick(s32 i) {
    s32 four;

    if (i > 2) {
        four = i << 2;
    }
    use(four);
}
"""
    assert module.variants(source, 'pick') == []


def test_a_base_assigned_on_every_path_is_left_alone():
    source = """extern u8 flags;
void pick(s32 i) {
    u8 *base;

    base = &flags;
    if (i) {
        use(base[0]);
    }
    use(base[1]);
}
"""
    assert module.variants(source, 'pick') == []


def test_declared_for_the_registry():
    entry = next(r for r in registry.declared() if r.module == 'split_multiple_rejoin')
    assert entry.families == module.FAMILIES
