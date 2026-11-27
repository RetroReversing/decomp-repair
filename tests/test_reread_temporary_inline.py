"""A value kept in a local ahead of the calls it is multiplied by, written whole at each read."""
from decomprepair import registry
from decomprepair import reread_temporary_inline as p

SOURCE = '''void spawn(s32 *out)
{
    s32 raw;
    s32 fast;
    s32 slow;

    raw = rand();
    if (out[0] != 0) {
        fast = ((u32) (raw & 0xFFFF) >> 8) + 0x266;
        out[1] = (sine(out[3]) * fast) >> 9;
        out[2] = (cosine(out[3]) * fast) >> 9;
    } else {
        slow = ((u32) (raw & 0xFFFF) >> 6) + 0x266;
        out[1] = (sine(out[3]) * slow) >> 8;
        out[2] = (cosine(out[3]) * slow) >> 8;
    }
}
'''


def test_every_arm_at_once_then_each():
    children = [child for _, child in p.variants(SOURCE, 'spawn')]
    assert len(children) == 3
    assert 'fast' not in children[0] and 'slow' not in children[0]
    assert children[0].count('((s32) (((u32) (raw & 0xFFFF) >> 8) + 0x266))') == 2
    assert children[0].count('((s32) (((u32) (raw & 0xFFFF) >> 6) + 0x266))') == 2


def test_declined_when_the_value_could_differ_or_nothing_is_crossed():
    one = '''void spawn(s32 *out)
{
    s32 raw;
    s32 fast;

    raw = rand();
    fast = (raw >> 8) + 0x266;
    out[1] = (sine(1) * fast) >> 9;
    out[2] = (cosine(1) * fast) >> 9;
}
'''
    assert len(p.variants(one, 'spawn')) == 1
    changed = one.replace('out[2] =', 'raw = 0;\n    out[2] =')
    memory = one.replace('(raw >> 8)', '(out[3] >> 8)')
    call = one.replace('(raw >> 8)', '(rand() >> 8)')
    nothing = one.replace('sine(1)', 'raw').replace('cosine(1)', 'raw')
    single = one.replace('(cosine(1) * fast) >> 9', '0')
    label = one.replace('out[2] =', 'again:\n    out[2] =')
    for source in (changed, memory, call, nothing, single, label):
        assert p.variants(source, 'spawn') == [], source


def test_the_module_declares_itself():
    assert any(repair.module == 'reread_temporary_inline' for repair in registry.declared())
