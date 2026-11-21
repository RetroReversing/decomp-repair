"""A repeated `&global` argument read once into a local, with the local's scope varied."""
from decomprepair import loop_address_hoist_repairs as h

# The loop of a GCC 2.7 N64 function (99%): the local stood for the address in the outer loop, and the nested goto
# loop kept the constant. That went from 465 to 405 in the judge; its first call kept the constant too.
SOURCE = '''typedef int s32;
typedef unsigned char u8;
typedef unsigned int u32;
extern s32 D_800E1310;
extern u8 D_80115088;
s32 reader(void *, s32, s32);
void setup(void *, s32);

void f(void) {
    s32 var_a;
    s32 var_b;
    u8 *tail;

    setup(&D_800E1310, 1);
    var_a = 0;
    tail = &D_80115088;
    do {
        s32 first = reader(&D_800E1310, 1, 1);
        *(&D_80115088 + var_a) = first;
        var_b = 0;
loop_3:
        tail[var_b] = reader(&D_800E1310, 1, 8);
        var_b += 1;
        if (var_b < 9) {
            goto loop_3;
        }
        *(&D_80115088 + var_a + 1) = reader(&D_800E1310, 1, 1);
        var_a += 1;
    } while (var_a < 11);
}
'''


def only(**kwargs):
    return [t for _, t in h.variants(SOURCE, 'f', **kwargs)]


def test_outer_loop_uses_the_local_and_the_nested_goto_loop_keeps_the_constant():
    # the 405 source: the assignment after `var_a = 0;`, the first call and the goto loop keep the constant
    wanted = SOURCE.replace('    u8 *tail;\n', '    u8 *tail;\n', 1)
    wanted = wanted.replace('    s32 var_a;\n', '    s32 *hoist_D_800E1310;\n    s32 var_a;\n', 1)
    wanted = wanted.replace('    var_a = 0;\n', '    var_a = 0;\n    hoist_D_800E1310 = &D_800E1310;\n', 1)
    wanted = wanted.replace('s32 first = reader(&D_800E1310', 's32 first = reader(hoist_D_800E1310', 1)
    wanted = wanted.replace('var_a + 1) = reader(&D_800E1310', 'var_a + 1) = reader(hoist_D_800E1310', 1)
    assert wanted in only()
    assert 'setup(&D_800E1310, 1);' in wanted and 'tail[var_b] = reader(&D_800E1310, 1, 8);' in wanted


def test_the_assignment_goes_before_the_loop_or_a_few_statements_above_it():
    texts = only()
    for placed in ('    tail = &D_80115088;\n    hoist_D_800E1310 = &D_800E1310;\n    do {',  # right before the loop
                   '    var_a = 0;\n    hoist_D_800E1310 = &D_800E1310;\n    tail',  # one up
                   '    setup(&D_800E1310, 1);\n    hoist_D_800E1310 = &D_800E1310;\n    var_a = 0;'):  # two up
        assert any(placed in t for t in texts), placed
    assert not any('hoist_D_800E1310 = &D_800E1310;\n    setup' in t and 'setup(&' in t for t in texts)


def test_one_variant_replaces_every_use():
    everything = [t for t in only() if 'setup(hoist_D_800E1310, 1);' in t and 'reader(&D_800E1310' not in t]
    assert len(everything) == 1
    assert everything[0].count('hoist_D_800E1310 = &D_800E1310;') == 1


def test_a_variant_is_proposed_only_for_a_plainly_declared_global_used_three_times():
    assert h.variants(SOURCE.replace('extern s32 D_800E1310;', 'extern volatile s32 D_800E1310;'), 'f') == []
    assert h.variants(SOURCE.replace('extern s32 D_800E1310;', ''), 'f') == []
    twice = SOURCE.replace('reader(&D_800E1310, 1, 8)', 'reader(0, 1, 8)').replace('reader(&D_800E1310, 1, 1);\n        var_a', 'reader(0, 1, 1);\n        var_a')
    assert h.variants(twice, 'f') == []
    assert h.variants(SOURCE, 'missing') == []


def test_only_a_bare_address_argument_is_replaced():
    indexed = SOURCE.replace('reader(&D_800E1310, 1, 8)', 'reader(&D_800E1310 + 1, 1, 8)')
    assert all('&D_800E1310 + 1' in t for t in [t for _, t in h.variants(indexed, 'f')])


def test_variants_are_distinct_bounded_and_never_the_source():
    texts = only()
    assert texts and len(texts) == len(set(texts)) <= h.LIMIT and SOURCE not in texts
