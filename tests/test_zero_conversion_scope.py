from decomprepair.zero_conversion_scope import variants

SOURCE = '''int f(void) {
    volatile int *p;
    long value;
    int zero;
    int present;
    do { value = *p; zero = 0; do { present = (short) (zero < value); } while (0); } while (0);
    return present;
}'''


def test_known_zero_from_an_already_loaded_local():
    result = variants(SOURCE, 'f')
    assert any('(unsigned short) value ^ ((unsigned int) value & 0xFFFF)' in s for _, s in result)
    assert all(s.count('value = *p;') == 1 for _, s in result)


def test_does_not_duplicate_volatile_or_uninitialized_reads():
    assert not variants(SOURCE.replace('long value;', 'volatile long value;'), 'f')
    assert not variants(SOURCE.replace('value = *p;', ''), 'f')
    assert not variants(SOURCE.replace('return present;', 'return present + *(&value);'), 'f')
    assert not variants(SOURCE, 'f', 'x86')


def test_uses_stable_pointer_to_avoid_extending_loaded_value_lifetime():
    source = SOURCE.replace('zero = 0;', 'zero = (unsigned short) value ^ ((unsigned int) value & 0xFFFF);')
    proposals = variants(source, 'f')
    assert any('(unsigned short) (unsigned int) p ^ ((unsigned int) p & 0xFFFF)' in s for _, s in proposals)
    assert all(s.count('value = *p;') == 1 for _, s in proposals)
    assert not variants(source.replace('volatile int *p;', 'volatile int *volatile p;'), 'f')
    assert not variants(source.replace('return present;', 'return *(&p) != 0;'), 'f')
