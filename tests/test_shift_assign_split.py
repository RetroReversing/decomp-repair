"""`x = (e) << k;` written as two statements."""
from decomprepair import registry
from decomprepair import shift_assign_split as m

SOURCE = '''void length(unsigned int size, unsigned char *dst)
{
    unsigned int total;
    int other;
    total = (((size & 0xFF) << 8) + (size >> 8)) << 16;
    other = (size + 1) << 2;
    dst[0] = (total + other) << 1;
}
'''


def texts(source=SOURCE):
    return [text for _, text in m.variants(source, 'length')]


def test_each_shift_gets_its_own_statement():
    found = texts()
    assert any('total = (((size & 0xFF) << 8) + (size >> 8));\n    total <<= 16;' in t
               and 'other = (size + 1);\n    other <<= 2;' in t for t in found)
    assert any('total <<= 16;' in t and 'other = (size + 1) << 2;' in t for t in found)


def test_only_an_outermost_shift_of_a_local_is_split():
    assert not texts(SOURCE.replace('(((size & 0xFF) << 8) + (size >> 8)) << 16', 'size + 1 << 16')
                     .replace('(size + 1) << 2', '(size) + (1) << 2'))
    assert all('dst[0] = (total + other) << 1;' in t for t in texts())


def test_it_is_registered():
    repair = registry.get('shift_assign_split')
    assert repair and registry.problems(repair) == []
