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
    assert len(result) == 1
    assert '(unsigned short) value ^ ((unsigned int) value & 0xFFFF)' in result[0][1]
    assert result[0][1].count('value = *p;') == 1


def test_does_not_duplicate_volatile_or_uninitialized_reads():
    assert not variants(SOURCE.replace('long value;', 'volatile long value;'), 'f')
    assert not variants(SOURCE.replace('value = *p;', ''), 'f')
    assert not variants(SOURCE.replace('return present;', 'return present + *(&value);'), 'f')
    assert not variants(SOURCE, 'f', 'x86')
