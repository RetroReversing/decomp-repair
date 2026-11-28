"""Guards that jump into a later if's then-arm, written as one chain (2090 -> 0 on a 297-instruction N64 update)."""
from decomprepair import registry
from decomprepair.goto_ladder_then_else import FAMILY, variants

SOURCE = """void update(Obj *obj, s32 arg)
{
    s32 mode;
    u8 state;

    state = obj->state;
    if (state == 3) {
        mode = 1;
        goto block_58;
    }
    if (state == 2) {
        mode = 1;
        goto block_58;
    }
    if (state != 1) {
        mode = 0;
block_58:
        draw(obj, mode, 0);
    } else {
        draw(obj, 1, 0);
        attach(arg, obj);
    }
    finish(obj);
}
"""


def _squash(text):
    return ''.join(text.split())


def test_each_path_calls_with_its_own_number_and_the_local_goes():
    children = [child for family, child in variants(SOURCE, 'update') if family == FAMILY]
    wanted = _squash("""if (state == 3) { draw(obj, 1, 0); } else if (state == 2) { draw(obj, 1, 0); }
        else if (state == 1) { draw(obj, 1, 0); attach(arg, obj); } else { draw(obj, 0, 0); } finish(obj);""")
    assert wanted in _squash(children[0])
    assert 'goto' not in children[0] and 'mode' not in children[0]


def test_the_last_test_is_also_offered_as_written_and_the_local_may_stay():
    children = [_squash(child) for _, child in variants(SOURCE, 'update')]
    assert len(children) == 4
    assert any(_squash('else if (state != 1) { draw(obj, 0, 0); } else {') in child for child in children)
    assert any(_squash('{ mode = 0; draw(obj, mode, 0); }') in child and 's32mode;' in child for child in children)


def test_a_local_read_after_the_join_keeps_its_assignments():
    source = SOURCE.replace('finish(obj);', 'finish(mode);')
    children = [child for _, child in variants(source, 'update')]
    assert children and all('mode = 1;' in child and 's32 mode;' in child for child in children)


def test_declines_when_the_label_has_another_way_in():
    assert variants(SOURCE.replace('finish(obj);', 'if (arg) { goto block_58; }'), 'update') == []
    assert variants(SOURCE.replace('    if (state == 2) {', '    tick();\n    if (state == 2) {'), 'update') == []
    assert variants(SOURCE.replace('    if (state == 3) {', '    if (arg) { spin(); } else if (state == 3) {'), 'update') == []


def test_registered():
    assert registry.get('goto_ladder_then_else').families == (FAMILY,)
