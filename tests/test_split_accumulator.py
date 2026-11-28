"""A running total m2c split into a temporary, as one variable."""
from decomprepair.split_accumulator import FAMILY, variants

SOURCE = """void load(void) {
    s32 total;
    s32 temp;
    s32 size;

    total = gStart;
    if (ready()) {
        temp = total + size;
        use((temp + 0xF) >> 4);
        total = temp + size;
    }
    gStart = total;
}
"""


def test_the_temporary_is_folded_into_the_total():
    ((family, text),) = variants(SOURCE, 'load')
    assert family == FAMILY
    assert 'total += size;\n        use((total + 0xF) >> 4);\n        total += size;' in text
    assert 'temp' not in text


def test_a_total_read_in_between_or_a_temporary_read_later_is_declined():
    assert variants(SOURCE.replace('use((temp + 0xF) >> 4);', 'use(total + temp);'), 'load') == []
    assert variants(SOURCE.replace('gStart = total;', 'gStart = total + temp;'), 'load') == []
