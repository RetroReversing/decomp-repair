from decomprepair import registry
from decomprepair.loop_counter_unify import FAMILY, REPAIR, variants

SOURCE = """void walk(Entity *e, u8 *map, s32 n) {
    s32 var_s1;
    s32 var_s1_2;
    long var_s1_3;
    u8 fill_i;
    s8 idx;
    u8 key;
    u8 *p;
    var_s1 = 0;
    do {
        e->a[var_s1] = 0;
        var_s1 += 1;
    } while (var_s1 < 0x40);
    for (fill_i = 0; fill_i < 0x80; fill_i++) {
        map[fill_i] = 0xFF;
    }
    p = e->base;
    key = p[5];
    idx = 0;
    if (key != 0xFF) {
        do {
            p += 8;
            map[key] = idx;
            key = p[5];
            idx += 1;
        } while (key != 0xFF);
    }
    var_s1_2 = 0;
    do {
        put(var_s1_2 & 0xFF);
        var_s1_2 += 1;
    } while (var_s1_2 < 0x10);
    var_s1_3 = 0xF;
    do {
        e->b[var_s1_3] = -1;
        var_s1_3 -= 1;
    } while (var_s1_3 >= 0);
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'walk') if f == FAMILY]


def test_every_word_counter_becomes_one_variable():
    first = children()[0]
    assert 'var_s1_2' not in first and 'var_s1_3' not in first
    assert first.count('var_s1 = 0;') == 2 and 'var_s1 = 0xF;' in first
    assert 'put(var_s1 & 0xFF);' in first


def test_byte_counters_of_both_signs_share_an_unsigned_variable():
    merged = [c for c in children() if 's8 idx;' not in c and 'u8 fill_i;' in c]
    assert merged
    assert 'map[key] = fill_i;' in merged[0] and 'for (fill_i = 0; fill_i < 0x80; fill_i++)' in merged[0]
    assert 'idx' not in merged[0]


def test_a_counter_read_after_its_last_loop_stays():
    tail = SOURCE[:-2] + '    use(var_s1_2);\n}\n'
    assert all('var_s1_2' in c for c in children(tail))


def test_a_counter_with_one_loop_alone_proposes_nothing():
    single = """void walk(Entity *e) {
    s32 i;
    i = 0;
    do {
        e->a[i] = 0;
        i += 1;
    } while (i < 4);
}
"""
    assert children(single) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
