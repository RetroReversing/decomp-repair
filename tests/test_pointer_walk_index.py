"""A do-while that walks a pointer and counts with a second variable, written as the counter indexing the table."""
from decomprepair.pointer_walk_index import FAMILY, variants

# The tail of a text-layout function (KMC GCC 2.7.2): a scale applied to every object of a table.
SAVED = '''extern void *table;
void f(f32 scale, s16 count) {
    void **p;
    void *o;
    s32 n;
    n = 0;
    if (count > 0) {
        p = &table;
        do {
            o = *p;
            n += 1;
            if (o != NULL) {
                G(o, 0x30) = scale;
            }
            p = p + 1;
        } while (n < count);
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_pointer_is_replaced_by_the_counter_indexing_the_table():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert len(out) == 1
    assert 'if (count > 0) { do { o = ((void **) &table)[n]; if (o != NULL) { G(o, 0x30) = scale; } n += 1; } while (n < count); }' in out[0]
    assert 'p = &table' not in out[0] and 'p + 1' not in out[0]


def test_a_pointer_read_after_the_loop_is_left_alone():
    assert variants(SAVED.replace('}\n}\n', '}\n    Q(p);\n}\n'), 'f') == []


def test_a_counter_not_zero_at_the_loop_is_left_alone():
    assert variants(SAVED.replace('n = 0;', 'n = 2;'), 'f') == []


def test_a_counter_read_in_the_body_is_left_alone():
    assert variants(SAVED.replace('G(o, 0x30) = scale;', 'G(o, 0x30) = n;'), 'f') == []


def test_a_loop_with_its_own_continue_is_left_alone():
    assert variants(SAVED.replace('if (o != NULL) {', 'if (o == NULL) { continue; }\n            if (o != NULL) {'), 'f') == []
