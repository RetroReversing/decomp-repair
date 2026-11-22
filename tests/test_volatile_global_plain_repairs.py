from decomprepair import volatile_global_plain_repairs as r

DRAFT = '''extern volatile unsigned short D_8010D6F8;
void f(void)
{
    s32 y;
    y = ((D_8010D6F8 - 1) & 0x3FF) << 14;
    y = *((volatile u16 *) (&D_8010D6F8));
    g(y);
}
'''


def _by_family(source=DRAFT):
    return dict(r.variants(source, 'f'))


def test_the_global_and_its_cast_accesses_become_plain():
    out = _by_family()['volatile_global_plain']
    assert 'extern unsigned short D_8010D6F8;' in out
    assert 'y = D_8010D6F8;' in out
    assert 'volatile' not in out


def test_the_flip_form_reads_the_opposite_signedness():
    out = _by_family()['volatile_global_plain_flip']
    assert 'extern short D_8010D6F8;' in out


def test_a_global_whose_address_escapes_is_left_alone():
    assert r.variants(DRAFT.replace('g(y);', 'g(&D_8010D6F8);'), 'f') == []


def test_a_plain_global_is_left_alone():
    assert r.variants(DRAFT.replace('volatile ', '', 1), 'f') == []


def test_a_global_the_function_does_not_use_is_left_alone():
    assert r.variants(DRAFT.replace('D_8010D6F8', 'D_80000000', 0).replace('y = ((D_8010D6F8 - 1) & 0x3FF) << 14;\n    y = *((volatile u16 *) (&D_8010D6F8));', 'y = 1;'), 'f') == []
