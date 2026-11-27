"""Arms with one body are one `||`, and with them a global declared `volatile` to fake its reloads is plain."""
from decomprepair import or_arm_merge as m
from decomprepair import registry

SOURCE = '''extern volatile f32 gAngle;
s32 f(void) {
    s32 v = 4;
    if (gAngle == 0.0f) v = 0;
    else if (gAngle == 360.0f) v = 0;
    else if (gAngle == 90.0f) v = 1;
    if (gAngle == 1.0f) { v = 2; }
    else if (v > 1 && gAngle == 2.0f) { v = 2; }
    return v;
}
'''


def test_merges_each_run_and_makes_the_global_plain():
    children = m.variants(SOURCE, 'f')
    family, merged = children[0]
    assert family == m.FAMILY
    assert 'if (gAngle == 0.0f || gAngle == 360.0f) v = 0;\n    else if (gAngle == 90.0f) v = 1;' in merged
    assert 'if (gAngle == 1.0f || (v > 1 && gAngle == 2.0f)) { v = 2; }\n    return v;' in merged
    assert children[1][0] == m.PLAIN_FAMILY and children[1][1].startswith('extern f32 gAngle;')
    assert len(children) == 4  # each run alone too


def test_different_bodies_are_left():
    assert m.variants(SOURCE.replace('v = 0;\n    else if (gAngle == 90', 'v = 3;\n    else if (gAngle == 90')
                      .replace('else if (v > 1 && gAngle == 2.0f) { v = 2; }', ''), 'f') == []


def test_declared_to_the_registry():
    assert any(r.module == 'or_arm_merge' for r in registry.declared())
