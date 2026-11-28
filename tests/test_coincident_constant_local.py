"""A constant that equals an earlier one by chance, stored through an `int` local of its own."""
from decomprepair import coincident_constant_local as t
from decomprepair import registry

SOURCE = '''void f(void)
{
    table[40].x = 80;
    table[40].y = 8;
    table[40].u = 512;
    table[41].x = 88;
    table[41].y = 8;
    table[41].u = 512;
    table[47].x = 8;
    table[47].y = 16;
    g();
}
'''


def test_the_first_store_of_a_value_into_another_member_gets_its_own_local():
    # A 301-instruction N64 font table set-up (SN GCC 2.8.1): the last entry's `x = 8` shared the register of every
    # row's `y = 8`; stored through an `int` local it loaded its own: 595 -> 120 in the app.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1
    assert '{\n  s32 wide_8;\n' in out[0]
    assert '    wide_8 = 8;\n    table[47].x = wide_8;\n' in out[0]
    assert out[0].count('= 8;') == 3


def test_rarer_pairs_come_first_and_a_block_boundary_ends_the_run():
    source = ('void f(int c)\n{\n    a->y = 5;\n    a->u = 5;\n    b->u = 5;\n    c1->x = 5;\n'
              '    if (c) {\n        d->w = 5;\n    }\n    e->v = 0;\n}\n')
    out = [text for _, text in t.variants(source, 'f')]
    assert len(out) == 2
    assert 'c1->x = wide_5;' in out[0]
    assert 'a->u = wide_5;' in out[1]


def test_nothing_when_the_value_stays_in_one_member_and_the_family_is_declared():
    assert t.variants('void f(void)\n{\n    a.y = 8;\n    b.y = 8;\n}\n', 'f') == []
    assert t.variants(SOURCE, 'missing') == []
    assert registry.declared()
    assert t.REPAIR['families'] == ('coincident_constant_local',)
