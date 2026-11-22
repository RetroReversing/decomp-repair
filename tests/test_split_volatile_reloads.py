from decomprepair.volatile_reload_repairs import split_reloads

SOURCE = """
extern u8 *volatile state;
void f(int enabled) {
    u8 *p;
    u8 *q;
    if (enabled) {
        p = state;
        p[5] = 0;
        q = state;
        p[4] = 0;
        q[0] = 1;
        p = state;
        p[3] = 0;
    }
}
"""


def test_offers_combined_and_individual_volatile_snapshots():
    combined, *individual = split_reloads(SOURCE, 'f')
    assert len(individual) == 3
    assert combined[0] == 'split_volatile_pointer_reloads'
    assert '__repair_pointer_reload_0[4] = 0;' in combined[1]
    assert '__repair_pointer_reload_1[0] = 1;' in combined[1]
    assert '__repair_pointer_reload_2[3] = 0;' in combined[1]
    assert combined[1].count('= state;') == 3


def test_rejects_escaping_and_loop_carried_snapshots():
    assert not split_reloads(SOURCE.replace('p[3] = 0;', 'p[3] = 0; consume(&p);'), 'f')
    assert not split_reloads(SOURCE.replace('if (enabled)', 'while (enabled)'), 'f')
    assert not split_reloads(SOURCE.replace('\n    }\n}', '\n    }\n    consume(p);\n}'), 'f')
