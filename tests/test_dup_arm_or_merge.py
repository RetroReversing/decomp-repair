"""An `||` written as nested `if`s with one arm twice, or as a jump past it, written back as one `||`."""
from decomprepair.dup_arm_or_merge import AND_FAMILY, FAMILY, variants

SOURCE = '''void f(s32 r)
{
    s32 temp_v0;
    s32 temp_v1;

    if (flag != 0) {
        if (!(r & 2)) {
            y = r;
            if (!(r & 1)) {
                temp_v1 = page;
                temp_v0 = 2;
                if (temp_v1 != temp_v0) {
                    x = 1;
                    goto block_end;
                }
            }
            temp_v1 = vx;
            x = temp_v1;
        } else {
            goto block_6;
        }
    } else if (r & 2) {
block_6:
        x = r;
    } else {
        if (!(r & 1)) {
            if (page != 2) {
                x = 1;
            } else {
                temp_v1 = vx;
                x = temp_v1;
            }
        } else {
            temp_v1 = vx;
            x = temp_v1;
        }
    }
block_end:
    x >>= 1;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_both_spellings_become_one_or_in_one_child():
    family, child = variants(SOURCE, 'f')[0]
    text = _squash(child)
    assert family == FAMILY
    assert 'y = r; if ((r & 1) || (page == 2)) { temp_v1 = vx; x = temp_v1; } else { x = 1; } } else {' in text
    assert '} else { if ((r & 1) || (page == 2)) { temp_v1 = vx; x = temp_v1; } else { x = 1; } } block_end:' in text
    assert 'goto block_end' not in text and 'temp_v0 = 2' not in text
    assert child.count('{') == child.count('}')


def test_the_and_spelling_and_each_site_alone_are_offered():
    children = variants(SOURCE, 'f')
    assert children[1][0] == AND_FAMILY
    assert 'if (!(r & 1) && (page != 2)) { x = 1; } else {' in _squash(children[1][1])
    assert len(children) == 6
    assert any('goto block_end' in child and '||' in child for _, child in children[2:])


def test_a_jump_that_is_not_the_fall_through_stays():
    source = '''void f(void)
{
    s32 a;

    while (g) {
        if (!a) {
            if (b != 2) {
                c();
                goto out;
            }
        }
        d();
    }
out:
    e();
    if (a) {
        if (!b) {
            if (c != 2) {
                x = 1;
                goto end;
            }
        }
        d();
    }
    other();
end:
    return;
}
'''
    assert variants(source, 'f') == []


def test_a_staged_value_that_is_read_again_keeps_the_site():
    source = SOURCE.replace('x >>= 1;', 'x >>= temp_v0;')
    assert all('goto block_end' in child for _, child in variants(source, 'f'))


def test_different_arms_are_not_merged():
    source = '''void f(void)
{
    if (a) {
        if (b) {
            c();
        } else {
            d();
        }
    } else {
        e();
    }
}
'''
    assert variants(source, 'f') == []
