"""join_call_arm_copy: the call a switch's join makes, written at the end of every arm that reaches it.

Shape of a 251-instruction KMC sound-selection function (saved best 210: `lhu $v1` before `move $a0,$v0` where the target
had the move first; with the call in each arm, 0)."""
from decomprepair import join_call_arm_copy as w

SOURCE = """s32 play(s32 id, f32 dist, u8 vol);
void update(s32 chan, void *marker, void *at, s32 flag);
extern void *table[];

void pick(void *obj, s32 arg1)
{
    s16 idx;
    u16 id;
    f32 d;

    d = nearest(obj, &idx);
    switch (*(u8 *) obj) {
    case 1:
        id = 0x18C;
        break;
    case 2:
    case 3:
        id = 0x158;
        if (arg1 != 0) {
            id = 5;
        }
        break;
    default:
        if (arg1) {
            id = 7;
            goto done;
        }
        id = 9;
        break;
    }
    done:
    update(play(id, d, 0xFF), table[(u16) idx], obj + 0x24, 0);
}
"""


def test_the_call_is_made_in_each_arm_and_the_join_reads_the_result():
    found = w.variants(SOURCE, 'pick')
    assert [family for family, _ in found] == [w.FAMILY]
    text = found[0][1]
    assert '    s32 join_result;\n' in text
    assert text.count('join_result = play(id, d, 0xFF);') == 4  # three breaks and the goto
    assert '{ join_result = play(id, d, 0xFF); goto done; }' in text
    assert 'update(join_result, table[(u16) idx], obj + 0x24, 0);' in text
    assert 'update(play(' not in text


def test_a_nested_loops_break_is_not_an_exit_of_the_switch():
    source = SOURCE.replace('        id = 0x18C;\n        break;',
                            '        id = 0x18C;\n        while (arg1) {\n            arg1 -= 1;\n            if (arg1 == 3) {\n'
                            '                break;\n            }\n        }\n        break;')
    text = w.variants(source, 'pick')[0][1]
    assert text.count('join_result = play(id, d, 0xFF);') == 4
    assert 'if (arg1 == 3) {\n                break;' in text


def test_a_result_variable_form_loses_its_statement():
    source = SOURCE.replace('    update(play(id, d, 0xFF), table[(u16) idx], obj + 0x24, 0);',
                            '    chan = play(id, d, 0xFF);\n    update(chan, table[(u16) idx], obj + 0x24, 0);')
    source = source.replace('    f32 d;\n', '    f32 d;\n    s32 chan;\n')
    text = w.variants(source, 'pick')[0][1]
    assert text.count('chan = play(id, d, 0xFF);') == 4
    assert '    chan = play(id, d, 0xFF);\n    update' not in text
    assert 'join_result' not in text


def test_a_switch_without_a_default_or_a_call_with_computed_arguments_is_left_alone():
    assert w.variants(SOURCE.replace('    default:', '    case 9:'), 'pick') == []
    assert w.variants(SOURCE.replace('play(id, d, 0xFF), table', 'play(id, rand(d), 0xFF), table'), 'pick') == []
    assert w.variants(SOURCE.replace('s32 play(', 'void play('), 'pick') == []


def test_a_goto_from_outside_the_switch_is_left_alone():
    source = SOURCE.replace('    d = nearest(obj, &idx);\n', '    d = nearest(obj, &idx);\n    if (arg1 == 4) {\n        id = 1;\n        goto done;\n    }\n')
    assert w.variants(source, 'pick') == []
