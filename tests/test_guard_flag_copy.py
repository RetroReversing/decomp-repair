"""A flag tested by an early return, read into a byte local just before the test."""
from decomprepair import guard_flag_copy as p
from decomprepair import registry

SOURCE = '''void draw(int x, int w)
{
    int done;

    done = 0;
    if (x < 0) {
        done = 1;
    }
    if (done) {
        return;
    }
    if (w < 0) {
        done = 1;
    }
    if (done != 0)
        return;
    use(x, w);
}
'''


def test_every_guard_gets_its_own_byte_copy_then_one_at_a_time():
    children = p.variants(SOURCE, 'draw')
    assert [family for family, _ in children] == [p.FAMILY] * 3
    both = children[0][1]
    assert '    unsigned char done_test1;\n' in both and '    unsigned char done_test2;\n' in both
    assert '    done_test1 = done;\n    if (done_test1) {\n        return;' in both
    assert '    done_test2 = done;\n    if (done_test2 != 0)\n        return;' in both
    assert 'done_test2' not in children[1][1]


def test_not_for_a_flag_a_byte_cannot_hold():
    assert p.variants(SOURCE.replace('done = 1;', 'done = x;'), 'draw') == []
    assert p.variants(SOURCE.replace('done = 1;', 'done++;'), 'draw') == []
    assert p.variants(SOURCE.replace('done = 1;', 'done = x & (w < 0);'), 'draw') == []
    assert p.variants(SOURCE.replace('done = 1;', 'done = w < 0;'), 'draw') != []


def test_not_for_a_global_or_a_guard_that_does_not_return_and_it_is_registered():
    assert p.variants(SOURCE.replace('    int done;\n', ''), 'draw') == []
    assert p.variants(SOURCE.replace('return;', 'use(x, w);'), 'draw') == []
    assert any(p.FAMILY in repair.families for repair in registry.declared())
