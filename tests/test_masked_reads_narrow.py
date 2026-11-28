"""A word counter only read under a mask, declared narrow."""
from decomprepair import masked_reads_narrow as m
from decomprepair import registry

SOURCE = '''void f(u32 n) {
    s32 var_s0;
    u32 temp;

    var_s0 = 0;
    while (1) {
        temp = var_s0 & 0xFFFF;
        if (n > (var_s0 & 0xFFFF)) {
            g(temp);
            var_s0 += 1;
        } else {
            break;
        }
    }
}
'''


def test_counter_becomes_u16():
    [(family, out)] = m.variants(SOURCE, 'f')
    assert family == 'masked_reads_narrow'
    assert 'u16 var_s0;' in out and '0xFFFF' not in out
    assert 'temp = var_s0;' in out and 'n > (var_s0)' in out and 'var_s0 += 1;' in out


def test_declines():
    for change in (('temp = var_s0 & 0xFFFF;', 'temp = var_s0;'),        # a whole-word read
                   ('temp = var_s0 & 0xFFFF;', 'temp = a + var_s0 & 0xFFFF;'),
                   ('var_s0 = 0;', 'var_s0 = -1;'),
                   ('var_s0 = 0;', 'var_s0 = 0x10000;'),
                   ('var_s0 += 1;', 'var_s0 = temp + 1;'),
                   ('g(temp);', 'g(&var_s0);'),
                   ('g(temp);', 'g(var_s0++);')):
        assert m.variants(SOURCE.replace(*change), 'f') == [], change


def test_registered():
    assert any(r.module == 'masked_reads_narrow' for r in registry.declared())


def test_a_for_counter_masked_inside_subscripts_is_narrowed():
    source = """void f(void)
{
    s32 i;

    for (i = 0; (i & 0xFFFF) < 10U; i++, tick())
    {
        counts[i & 0xFFFF] = 0;
        use(table[i & 0xFFFF][2]);
    }
}
"""
    children = [child for _, child in m.variants(source, 'f')]
    assert children and 'u16 i;' in children[0]
    assert 'counts[i] = 0;' in children[0] and 'table[i][2]' in children[0] and '(i) < 10U' in children[0]


def test_a_for_header_that_reads_the_counter_bare_is_left():
    source = """void f(void)
{
    s32 i;

    for (i = 0; i++ < 10;)
    {
        counts[i & 0xFFFF] = 0;
    }
}
"""
    assert m.variants(source, 'f') == []
