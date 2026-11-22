import re

from decomprepair.constant_store_bracket import DROP_FAMILY, FAMILIES, FAMILY, variants

# A defaults reset: one literal (5) stored to two globals, with one-shot literals stored before it. The first store of
# `c` is overwritten by the second with other stores between them, so both are emitted.
SOURCE = '''extern unsigned char a, b, c, d, e, f, g, h, i, j, k, l, m, n;
void reset(void)
{
  do {
    unsigned char hold = 0xFF;
    a = 0xA1; b = 0x61; c = 5; d = 0xEE; e = 0x41; f = 0x11; g = 0;
    h = hold; i = hold; j = 0; k = 0;
    c = 5; l = 0; m = 5;
  } while (0);
}
'''


def stores(source):
    return re.findall(r'(?<![\w])(\w+) = (\w+);', source.replace('unsigned char hold = 0xFF;', ''))


def of(family, source=SOURCE):
    return [text for found, text in variants(source, 'reset') if found == family]


def test_the_drop_and_the_move_together_are_one_child():
    # target order of the machine: the two stores of `c` bracket the three one-shot stores d, e, f
    wanted = [('a', '0xA1'), ('b', '0x61'), ('g', '0'), ('h', 'hold'), ('i', 'hold'), ('j', '0'),
              ('k', '0'), ('c', '5'), ('d', '0xEE'), ('e', '0x41'), ('f', '0x11'), ('l', '0'), ('m', '5')]
    assert any(stores(text) == wanted for text in of(FAMILY))
    assert {family for family, _ in variants(SOURCE, 'reset')} <= set(FAMILIES)


def test_the_overwritten_store_is_dropped_alone_too():
    dropped = of(DROP_FAMILY)
    assert len(dropped) == 1
    assert stores(dropped[0]) == [s for k, s in enumerate(stores(SOURCE)) if k != stores(SOURCE).index(('c', '5'))]


def test_a_move_never_loses_or_adds_a_store():
    for text in of(FAMILY):
        stored = stores(text)
        assert len(stored) in (len(stores(SOURCE)), len(stores(SOURCE)) - 1)
        assert not [s for s in stored if stored.count(s) > stores(SOURCE).count(s)]


def test_a_store_that_something_reads_in_between_is_not_dropped():
    source = SOURCE.replace('c = 5; l = 0;', 'n = c; c = 5; l = 0;')
    assert variants(source, 'reset') == [] or all(text.count('c = 5') == 2 for text in of(DROP_FAMILY, source))


def test_calls_and_locals_are_left_alone():
    source = '''extern unsigned char a, b;
void reset(void)
{
  int x;
  x = 3; a = 7; foo(); b = 7; a = 7;
}
'''
    assert variants(source, 'reset') == []
