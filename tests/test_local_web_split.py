"""A function-level scratch local assigned afresh in many arms, split into one local per assignment web."""
import re

from decomprepair import local_web_split as w
from decomprepair.registry import declared

ARMS = '''void f(void *arg0, s32 mode) {
    s32 *packet;
    u32 first;
    register u32 second;

    if (mode == 1) {
        first = 0xFC40FE03;
        packet = D_cursor;
        second = 0xFF0FF37F;
        D_cursor = packet + 2;
        packet[0] = first;
        packet[1] = second;
        return;
    }
    if (mode == 2) {
        first = 0xFC119623;
        second = 0xFF2E0000;
        packet = D_cursor;
        D_cursor = packet + 2;
        packet[0] = first;
        packet[1] = second | 0xFF7F;
        return;
    }
    if (mode == 3) {
        packet = D_cursor;
        D_cursor = packet + 2;
        packet[0] = 0;
        packet[1] = 0;
    }
}
'''


def children(source, name='f'):
    return [t for fam, t in w.variants(source, name) if fam == w.FAMILY]


def test_every_arm_gets_its_own_locals():
    everything = children(ARMS)[-2]
    assert everything.count('packet_') >= 6
    for k in (1, 2, 3):
        assert f's32 *packet_{k};' in everything
    assert 'u32 first_1;' in everything and 'u32 first_2;' in everything
    assert 'register u32 second_1;' in everything
    assert '    s32 *packet;\n' not in everything
    assert 'packet_1 = D_cursor;' in everything and 'packet_2[1] = second_2 | 0xFF7F;' in everything


def test_register_dropped_child_and_single_local_children():
    out = children(ARMS)
    assert any('register' not in t.split('{', 1)[1].split('if (mode', 1)[0] for t in out)
    alone = [t for t in out if 'first_1' not in t and 'packet_1' in t]
    assert alone and 'u32 first;' in alone[0]


def test_one_arm_alone_is_not_a_web_split():
    single = ARMS.split('if (mode == 2)')[0] + '}\n'
    assert children(single) == []


def test_read_before_assignment_leaves_the_local():
    source = ARMS.replace('    if (mode == 1) {', '    D_out = first;\n    if (mode == 1) {', 1)
    assert not any('first_1' in t for t in children(source))


def test_address_taken_leaves_the_local():
    source = ARMS.replace('D_cursor = packet + 2;', 'keep(&packet); D_cursor = packet + 2;', 1)
    assert not any('packet_1' in t for t in children(source))


def test_a_label_in_the_web_keeps_its_name():
    source = '''void f(s32 a, s32 *out) {
    s32 v;

    if (a == 1) {
        v = 1;
top:
        out[0] = v;
        if (out[1]) goto top;
        return;
    }
    if (a == 2) {
        v = 2;
        out[2] = v;
        return;
    }
    if (a == 3) {
        v = 3;
        out[3] = v;
    }
}
'''
    out = children(source)
    assert out
    everything = out[-1]
    assert 'v = 1;' in everything and 'out[0] = v;' in everything
    assert 'v_1 = 2;' in everything and 'out[3] = v_2;' in everything


def test_inner_assignment_visible_after_its_block_merges_webs():
    source = '''void f(s32 a, s32 *out) {
    s32 v;

    v = 1;
    if (a) {
        v = 2;
    }
    out[0] = v;
    if (a == 3) {
        v = 9;
        out[1] = v;
    }
}
'''
    # `v = 2` can reach `out[0] = v`, so it stays with `v = 1`; only the last arm is a web of its own
    assert children(source)
    for text in children(source):
        assert 'v = 1;' in text and 'v = 2;' in text and 'out[0] = v;' in text or 'v_1 = 1;' in text and 'v_1 = 2;' in text


def test_inner_assignment_in_a_block_that_returns_is_its_own_web():
    source = '''void f(s32 a, s32 *out) {
    s32 v;

    v = a & 7;
    if (v == 1) {
        v = 0x10;
        out[0] = v;
        return;
    }
    out[1] = v;
}
'''
    text = children(source)[-1]
    assert 'v_1 = a & 7;' in text and 'v_2 = 0x10;' in text and 'out[1] = v_1;' in text and 'v_1 == 1' in text


def test_loop_around_inner_assignment_merges_webs():
    source = '''void f(s32 a, s32 *out) {
    s32 v;

    v = 1;
    while (a--) {
        out[0] = v;
        if (a == 5) {
            v = 2;
        }
    }
    v = 3;
    out[1] = v;
}
'''
    for text in children(source):
        assert 'v = 2;' in text.replace('v_1 = 2;', 'v = 2;') and 'out[0] = v;' in text.replace('out[0] = v_1;', 'out[0] = v;')
        assert re.search(r'v(_\d)? = 1;', text) and re.search(r'v(_\d)? = 2;', text)
        # the first assignment and the one in the loop stay one local
        one = re.search(r'(v(?:_\d)?) = 1;', text).group(1)
        assert f'{one} = 2;' in text


def test_declared_for_the_registry():
    assert any(r.module == 'local_web_split' for r in declared())
