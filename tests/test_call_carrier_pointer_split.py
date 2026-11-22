"""call_carrier_pointer_split: stray trailing pointer arguments dropped and a reused pointer local split, one child.

Synthetic shape of a 140-instruction KMC menu function (60 -> 0 together; 790 and 60 alone): m2c passes the pointer
local the argument register still holds as a second argument of one-argument callees, and reuses that local for two loads
of the same field around a store through it."""
from decomprepair import call_carrier_pointer_split as s

SOURCE = '''s32 show();
s32 flush();
s32 tick();

void draw(void *obj, s32 mode) {
    void *temp;
    void *other;
    temp = *(void **)obj;
    *(s32 *)((char *)temp + 0x10) = 1;
    temp = *(void **)obj;
    *(s32 *)((char *)temp + 0x28) = mode;
    show(3, temp);
    other = *(void **)((char *)obj + 4);
    *(s32 *)((char *)other + 0x28) = mode;
    flush(3, other);
    tick(temp);
}
'''


def test_the_combination_is_one_child_with_both_edits():
    found = dict((family, text) for family, text in s.variants(SOURCE, 'draw'))
    text = found[s.FAMILY]
    assert 'show(3);' in text and 'flush(3);' in text
    assert 'void *temp_b1;' in text and 'temp_b1 = *(void **)obj;' in text
    assert '*(s32 *)((char *)temp_b1 + 0x28) = mode;' in text
    assert 'temp = *(void **)obj;\n    *(s32 *)((char *)temp + 0x10) = 1;' in text
    assert 'tick(temp_b1);' in text  # a one-argument call keeps its argument, read from the second value


def test_each_half_is_offered_alone():
    families = [family for family, _ in s.variants(SOURCE, 'draw')]
    assert families == [s.FAMILY, s.DROP_FAMILY, s.SPLIT_FAMILY]


def test_a_parameter_or_a_declared_prototype_is_left_alone():
    typed = SOURCE.replace('s32 show();', 's32 show(s32, void *);').replace('s32 flush();', 's32 flush(s32, void *);')
    assert [family for family, _ in s.variants(typed, 'draw')] == [s.SPLIT_FAMILY]
    param = SOURCE.replace('show(3, temp);', 'show(3, obj);').replace('flush(3, other);', 'flush(3, mode);')
    assert [family for family, _ in s.variants(param, 'draw')] == [s.SPLIT_FAMILY]


def test_a_loop_goto_or_outer_read_declines_the_split():
    looped = SOURCE.replace('    tick(temp);', '    while (mode--) tick(temp);')
    assert s.variants(looped, 'draw') == []
    outside = SOURCE.replace('void draw(void *obj, s32 mode) {\n', 'void draw(void *obj, s32 mode) {\n    if (mode) {\n').replace(
        '    tick(temp);\n}', '    }\n    tick(temp);\n}')
    families = [family for family, _ in s.variants(outside, 'draw')]
    assert s.SPLIT_FAMILY not in families and s.FAMILY not in families
