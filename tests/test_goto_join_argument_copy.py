"""goto_join_argument_copy: a call's first argument copied on every path that reaches a `goto` join.

Shape of a 157-instruction KMC effect spawner (m2c's three-arm switch assigning the second and third argument and
jumping to one shared call; the copy on all three paths took it 225 -> 160, with the callee's width and the debug
statement boundary then 100 and 0)."""
from decomprepair import goto_join_argument_copy as w

SOURCE = """void *spawn(s32 kind);
void apply(void *obj, s32 a, s32 b);
extern s16 table_a[];
extern s16 table_b[];

void *build(s32 kind, s32 sel, u16 idx, u16 x, u16 y)
{
    s32 scale;
    s32 var_a1;
    s32 var_a2;
    void *obj;

    obj = spawn(kind);
    if (sel & 1)
    {
        switch (idx)
        {
            case 0:
                scale = idx * 4;
                var_a1 = table_a[scale];
                var_a2 = table_b[scale];
                goto join;
            case 1:
                var_a1 = table_a[1];
                var_a2 = table_b[1];
                goto join;
            case 2:
                goto direct;
        }
    }
    else
    {
        direct:
        var_a1 = x;
        var_a2 = y & 0xFFFF;
        join:
        apply(obj, var_a1, var_a2);
    }
    return obj;
}
"""


def test_the_copy_is_set_beside_the_other_arguments_on_every_path():
    found = w.variants(SOURCE, 'build')
    assert [family for family, _ in found] == [w.FAMILY] * 2
    beside = found[0][1]
    assert 'void *join_arg;' in beside and 'apply(join_arg, var_a1, var_a2);' in beside
    assert beside.count('join_arg = obj;') == 3
    assert beside.index('join_arg = obj;') < beside.index('var_a1 = table_a[scale];')
    assert beside.index('scale = idx * 4;') < beside.index('join_arg = obj;')
    assert beside.index('join_arg = obj;\n        var_a1 = x;') < beside.index('join:')


def test_the_second_child_sets_it_just_before_each_jump_and_the_label():
    near = w.variants(SOURCE, 'build')[1][1]
    assert near.count('join_arg = obj;') == 3
    assert 'join_arg = obj;\n                goto join;' in near
    assert 'join_arg = obj;\n        join:' in near


def test_a_conditional_goto_is_left_alone():
    source = SOURCE.replace('                goto join;\n            case 1:', '                if (x) goto join;\n            case 1:')
    assert w.variants(source, 'build') == []


def test_a_label_one_jump_reaches_is_not_a_join():
    source = SOURCE.replace('                goto join;\n            case 2:', '                goto direct;\n            case 2:')
    assert w.variants(source, 'build') == []


def test_it_does_not_run_twice():
    again = w.variants(SOURCE, 'build')[0][1]
    assert w.variants(again, 'build') == []
