from decomprepair import registry
from decomprepair.loop_bound_local import FAMILY, REPAIR, variants

SOURCE = """void fill(s32 *a) {
    s32 i;

    for (i = 0; i < D_80001000; i++) {
        a[i] = 0;
    }
}
"""
HEADER = 'extern s32 D_80001000;\n'


def kids(source=SOURCE, header=HEADER):
    return [c for f, c in variants(source, 'fill', header) if f == FAMILY]


def test_a_global_bound_is_read_once_into_a_local_above_the_loop():
    out = kids()
    assert out and 'n_80001000 = D_80001000;\n    for (i = 0; i < n_80001000; i++)' in out[0]
    assert out[0].index('s32 n_80001000;') < out[0].index('n_80001000 = D_80001000;')


def test_a_loop_with_a_call_or_a_write_to_the_global_keeps_its_read():
    assert not kids(SOURCE.replace('a[i] = 0;', 'a[i] = g(i);'))
    assert not kids(SOURCE.replace('a[i] = 0;', 'D_80001000 = 3;'))


def test_a_bound_whose_type_the_header_does_not_say_is_left_alone():
    assert not kids(header='')


def test_a_while_loop_and_a_flipped_test_are_read_too():
    assert kids(SOURCE.replace('for (i = 0; i < D_80001000; i++)', 'while (D_80001000 > i)').replace('a[i] = 0;', 'a[i++] = 0;'))


def test_it_is_registered():
    repair = registry.get('loop_bound_local')
    assert repair and registry.problems(repair) == [] and REPAIR['families'] == (FAMILY,)
