"""A local used by one arm only, written as a variable that is idle there."""
from decomprepair import idle_arm_local_merge as m

SOURCE = """void panel(void) {
    s32 var_s3;
    s32 var_s3_2;

    var_s3 = 0x50;
    if (mode != 0) {
        var_s3_2 = 0x32;
        do {
            draw(var_s3_2);
            var_s3_2 -= 0x14;
        } while (var_s3_2 > 0);
        return;
    }
    draw(var_s3);
}
"""


def test_the_arm_local_becomes_the_idle_one():
    children = m.variants(SOURCE, 'panel')
    assert [family for family, _ in children] == [m.FAMILY]
    child = children[0][1]
    assert 'var_s3_2' not in child
    assert 'var_s3 = 0x32;' in child and 'var_s3 -= 0x14;' in child and 'draw(var_s3);' in child


def test_not_when_the_value_is_read_after_the_arm():
    assert m.variants(SOURCE.replace('        return;\n', ''), 'panel') == []


def test_an_else_arm_may_keep_the_other_value():
    source = SOURCE.replace('        return;\n    }\n    draw(var_s3);\n', '    } else {\n        draw(var_s3);\n    }\n')
    assert [family for family, _ in m.variants(source, 'panel')] == [m.FAMILY]


def test_not_inside_a_loop():
    source = SOURCE.replace('    if (mode != 0) {', '    while (more()) {\n    if (mode != 0) {')[:-2] + '}\n}\n'
    assert m.variants(source, 'panel') == []


def test_not_when_the_arm_also_reads_the_other():
    assert m.variants(SOURCE.replace('draw(var_s3_2);', 'draw(var_s3_2 + var_s3);'), 'panel') == []
