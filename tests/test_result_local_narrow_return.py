from decomprepair import registry
from decomprepair import result_local_narrow_return as repair

SOURCE = """s8 f(s32 limit) {
    s32 pos = -1;
    u32 i;

    for (i = 0; i < 10; i++) {
        if (table[i] < limit) {
            pos = i;
            last = i;
            i = 11;
        }
    }
    return pos;
}
"""


def test_the_returned_local_takes_the_return_type():
    (family, child), = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert child == SOURCE.replace('s32 pos = -1;', 's8 pos = -1;')


def test_a_cast_return_qualifies():
    assert repair.variants(SOURCE.replace('return pos;', 'return (s8) pos;'), 'f')


def test_a_local_read_elsewhere_or_a_wide_return_is_left_alone():
    assert not repair.variants(SOURCE.replace('last = i;', 'last = pos;'), 'f')
    assert not repair.variants(SOURCE.replace('pos = i;', 'last = pos = i;'), 'f')
    assert not repair.variants(SOURCE.replace('s8 f(', 's32 f('), 'f')
    assert not repair.variants(SOURCE.replace('pos = i;', 'pos >>= 1;'), 'f')
    assert not repair.variants(SOURCE.replace('return pos;', 'return other;'), 'f')


def test_it_is_registered():
    assert repair.FAMILY in str(registry.declared())


def test_a_word_function_that_casts_its_result_gives_the_width():
    cast = SOURCE.replace('s8 f(', 's32 f(').replace('return pos;', 'return (s8) pos;')
    (_, child), = repair.variants(cast, 'f')
    assert 's8 pos = -1;' in child
    assert not repair.variants(cast.replace('(s8) pos;', '(s8) pos;\n    return pos;'), 'f')
