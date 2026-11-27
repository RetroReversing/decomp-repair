from decomprepair.registry import declared
from decomprepair.word_temp_block_copy import FAMILY, variants

# the saved best of a KMC GCC 2.7.2 -O1 record-array copy (an N64 game): three temporaries per three-word record
SOURCE = """extern void *D_800B2D9C;

void f(void) {
    s32 i;
    char *base;
    char *p;
    s32 v0, v1, v2;
    s32 w0, w1, w2;
    char *tb;
    i = 0;
    do {
        base = (char *)D_800B2D9C;
        p = (char *)(i * 12 + (s32)base);
        v0 = *(s32 *)(p + 0xDA4);
        v1 = *(s32 *)(p + 0xDA8);
        v2 = *(s32 *)(p + 0xDAC);
        *(s32 *)(p + 0x75C) = v0;
        *(s32 *)(p + 0x760) = v1;
        *(s32 *)(p + 0x764) = v2;
        i++;
    } while (i < 0x60);
    tb = (char *)D_800B2D9C;
    w0 = *(s32 *)(tb + 0x1224);
    w1 = *(s32 *)(tb + 0x1228);
    w2 = *(s32 *)(tb + 0x122C);
    *(s32 *)(tb + 0x72C) = w0;
    *(s32 *)(tb + 0x730) = w1;
    *(volatile s32 *)(tb + 0x734) = w2;
}
"""

LOOP = '*(__repair_words3 *) ((s8 *) p + 0x75C) = *(__repair_words3 *) ((s8 *) p + 0xDA4);'
TAIL = '*(__repair_words3 *) ((s8 *) tb + 0x72C) = *(__repair_words3 *) ((s8 *) tb + 0x1224);'


def test_each_run_and_both_runs_become_struct_assignments():
    children = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert len(children) == 3
    both = children[-1]
    # the matched source (25 -> 0): both runs, the volatile stand-in gone, one typedef before the function
    assert LOOP in both and TAIL in both and 'volatile' not in both
    assert both.count('typedef struct { s32 w[3]; } __repair_words3;') == 1
    assert both.index('typedef') < both.index('void f(void)')
    assert '= v0;' not in both and 'w2 =' not in both
    assert LOOP in children[0] and TAIL not in children[0]


def test_a_temporary_read_elsewhere_or_an_offset_gap_is_left_alone():
    read = SOURCE.replace('    i++;\n', '    i += v1;\n')
    assert all(LOOP not in text for _, text in variants(read, 'f'))
    gap = SOURCE.replace('(p + 0xDA8)', '(p + 0xDB0)')
    assert all(LOOP not in text for _, text in variants(gap, 'f'))
    swapped = SOURCE.replace('*(s32 *)(p + 0x760) = v1;', '*(s32 *)(p + 0x760) = v2;')
    assert all(LOOP not in text for _, text in variants(swapped, 'f'))


def test_m2c_field_spelling_and_the_registry():
    m2c = """void g(void *a, void *b) {
    s32 t0;
    s32 t1;
    t0 = M2C_FIELD(b, s32 *, 0x10);
    t1 = M2C_FIELD(b, s32 *, 0x14);
    M2C_FIELD(a, s32 *, 0) = t0;
    M2C_FIELD(a, s32 *, 4) = t1;
}
"""
    [(family, text)] = variants(m2c, 'g')
    assert '*(__repair_words2 *) ((s8 *) a + 0x0) = *(__repair_words2 *) ((s8 *) b + 0x10);' in text
    assert any(FAMILY in r.families for r in declared())
