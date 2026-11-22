from decomprepair.copy_sink_after_call_repairs import FAMILY, variants

SOURCE = '''void f(s32 n)
{
    u8 *buffer;
    u8 *walk;
    buffer = alloc(n);
    {
        u8 *dest = buffer;
        walk = buffer;
        fill(dest, n);
    }
    loop(walk);
}
'''


def sunk(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_copy_follows_the_call_and_then_its_block():
    inside, outside = sunk()
    assert '        fill(dest, n);\n        walk = buffer;\n    }\n' in inside
    assert '        fill(dest, n);\n    }\n    walk = buffer;\n    loop(walk);' in outside
    assert 'walk = buffer;\n        u8' not in inside


def test_a_call_that_mentions_the_copy_is_not_crossed():
    assert not sunk(SOURCE.replace('fill(dest, n)', 'fill(walk, n)'))


def test_a_copy_before_something_that_is_not_a_call_stays():
    assert not sunk(SOURCE.replace('fill(dest, n);', 'n = 3;'))
