"""pointer_reload_web_split: a pointer local reloaded from a global several times, one local per load, in one child.

Synthetic shape of a 136-instruction KMC menu reset (165 -> 60: one web split alone changes nothing, all of them
together rotate the registers as the target has them)."""
from decomprepair import pointer_reload_web_split as s

SOURCE = '''extern u8 * volatile gState;
void reset(void)
{
    u8 *p;
    u8 *q;
    if ((p = gState) != NULL)
    {
        p[7] = 0;
        p = gState;
        p[0x2F] = 0;
        q = gState;
        *((s32 *) (p + 0x20)) = 0;
        q[0x28] = 0;
        p = gState;
        *((s32 *) q) = 0;
        p[0x29] = 0;
        q = gState;
        q[0x2D] = 0;
    }
}
'''


def test_every_load_gets_a_pointer_of_its_own_in_one_child():
    found = s.variants(SOURCE, 'reset')
    family, text = found[0]
    assert family == s.FAMILY
    assert 'p[7] = 0;' in text                                   # the condition's value keeps its name
    assert 'p_b1 = gState;\n        p_b1[0x2F] = 0;' in text
    assert '*((s32 *) (p_b1 + 0x20)) = 0;' in text and 'p_b2 = gState;' in text and 'p_b2[0x29] = 0;' in text
    assert 'q = gState;\n        *((s32 *) (p_b1' in text      # q's first load keeps the name, the second is split
    assert 'q_b1 = gState;' in text and 'q_b1[0x2D] = 0;' in text and 'q[0x28] = 0;' in text
    assert 'u8 *p_b1;' in text and 'u8 *p_b2;' in text and 'u8 *q_b1;' in text


def test_each_local_is_offered_alone():
    found = s.variants(SOURCE, 'reset')
    assert [family for family, _ in found] == [s.FAMILY, s.LOCAL_FAMILY, s.LOCAL_FAMILY]
    assert 'q_b1' not in found[1][1] and 'q_b1' in found[2][1]


def test_a_loop_label_goto_or_later_read_declines():
    looped = SOURCE.replace('    if ((p = gState) != NULL)', '    while (gFlag)\n    if ((p = gState) != NULL)')
    assert s.variants(looped, 'reset') == []
    outside = SOURCE.replace('        q[0x2D] = 0;\n    }\n', '        q[0x2D] = 0;\n    }\n    g(q);\n')
    assert all('q_b1' not in text for _, text in s.variants(outside, 'reset'))
    inner = SOURCE.replace('        p[0x2F] = 0;', '        lab:\n        p[0x2F] = 0;')
    assert all('p_b2' not in text for _, text in s.variants(inner, 'reset'))


def test_a_parameter_or_an_address_taken_pointer_is_left_alone():
    param = SOURCE.replace('void reset(void)', 'void reset(u8 *p)').replace('    u8 *p;\n', '')
    assert all('p_b' not in text for _, text in s.variants(param, 'reset'))
    escaped = SOURCE.replace('        p[7] = 0;', '        g(&p);')
    assert all('p_b' not in text for _, text in s.variants(escaped, 'reset'))
