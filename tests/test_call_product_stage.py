"""A product of a call and a store of its shifted result, written in steps through the function's own locals."""
from decomprepair.call_product_stage import FAMILY, variants

SOURCE = """s16 wave_y(s16);
s16 wave_x(s16);
s32 heading(s32);

void launch(Body *body, s32 speed) {
    s32 len;
    s32 dir;
    s16 angle;
    s32 vx;
    s32 vy;

    dir = heading(body->x);
    angle = dir % 0x1000;
    vx = wave_x(angle) * speed;
    len = wave_y(angle) * speed;
    body->x = -(vx >> 12);
    body->y = len >> 12;
}
"""


def _bodies():
    return [child for family, child in variants(SOURCE, 'launch') if family == FAMILY]


def test_whole_step_is_one_child():
    # the combination that matched: both narrow calls extended through a free local, both products and stores in steps
    full = [c for c in _bodies() if 's32 wave_x(s16);' in c and 's32 wave_y(s16);' in c and 'body->y = len;' in c]
    assert full
    child = full[0]
    assert ' = wave_x(angle) << 16;' in child
    assert 'vx *= speed;' in child and 'len *= speed;' in child
    assert 'vx >>= 12;' in child and 'len >>= 12;' in child
    assert '= -vx;' in child


def test_single_edits_are_offered():
    assert any('vx = wave_x(angle);\n    vx *= speed;' in c and 's16 wave_x(s16);' in c for c in _bodies())
    assert any('len >>= 12;\n    body->y = len;' in c and 'vx * speed' not in c and 'wave_x(angle) * speed' in c
               for c in _bodies())


def test_return_is_widened_only_for_a_single_call():
    twice = SOURCE.replace('    body->y = len >> 12;\n', '    body->y = len >> 12;\n    body->z = wave_x(angle);\n')
    assert not any('s32 wave_x(s16);' in c for _, c in variants(twice, 'launch'))


def test_a_live_value_is_not_shifted_in_place():
    live = SOURCE.replace('    body->y = len >> 12;\n', '    body->y = len >> 12;\n    body->z = len;\n')
    assert not any('len >>= 12;' in c for _, c in variants(live, 'launch'))


def test_volatile_and_goto_decline():
    assert variants(SOURCE.replace('s32 vy;', 'volatile s32 vy;'), 'launch') == []


def test_a_fence_around_the_arms_is_no_loop():
    # a weight scope wraps the arms that set `dir`; `dir` is still free at the store after it
    fenced = SOURCE.replace("    dir = heading(body->x);\n",
                            "    do {\n    if (speed > 0) {\n        dir = heading(body->x);\n    } else {\n"
                            "        dir = heading(body->y);\n    }\n")
    fenced = fenced.replace("    body->y = len >> 12;\n", "    body->y = len >> 12;\n    } while (0);\n")
    assert any('dir = -vx;' in c for _, c in variants(fenced, 'launch'))


def test_a_product_takes_over_a_finished_local():
    source = SOURCE.replace('    len = wave_y(angle) * speed;', '    vy = wave_y(angle) * speed;')
    source = source.replace('    dir = heading(body->x);\n', '    len = heading(body->y);\n    dir = heading(body->x) + len;\n')
    source = source.replace('body->y = len >> 12;', 'body->y = vy >> 12;')
    assert any('len = wave_y(angle) << 16;' not in c and 'len >>= 12;' in c and 'body->y = len;' in c
               for _, c in variants(source, 'launch'))
