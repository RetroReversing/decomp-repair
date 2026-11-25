"""`f(K + n++, ..);` as `f(K + n, ..); n++;` (an N64 level loader's spilled counter, 615 -> 220)."""
from decomprepair.call_arg_postinc_statement import FAMILY, variants

SOURCE = """void load(s32 base, s32 count, Entry *tbl)
{
    s32 n;
    s32 i;
    s32 t2;
    Entry *e;

    n = 0;
    e = tbl;
    for (i = 0; i < count; i++) {
        t2 = base + 1;
        use(0xA9 + n++, i + t2, e->f);
        e++;
    }
}
"""


def test_the_increment_becomes_the_statement_after_the_call():
    found = variants(SOURCE, 'load')
    assert [family for family, _ in found] == [FAMILY]
    assert '        use(0xA9 + n, i + t2, e->f);\n        n++;\n        e++;\n' in found[0][1]


def test_a_counter_read_twice_address_taken_or_global_is_left_alone():
    assert variants(SOURCE.replace('i + t2', 'n + t2'), 'load') == []
    assert variants(SOURCE.replace('e++;', 'e++;\n        bump(&n);'), 'load') == []
    assert variants(SOURCE.replace('n++', 'gCount++'), 'load') == []


def test_an_assigned_call_and_a_decrement_and_every_site_together():
    source = SOURCE.replace('use(0xA9 + n++, i + t2, e->f);', 'i = pick(n--, 3);\n        use(0xA9 + count++, i, 0);')
    found = variants(source, 'load')
    assert len(found) == 3
    together = found[-1][1]
    assert '        i = pick(n, 3);\n        n--;\n' in together
    assert '        use(0xA9 + count, i, 0);\n        count++;\n' in together
