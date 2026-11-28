from decomprepair import float_negation_cast_order, float_pair_vec3, guard_conjunct_hoist_split

BUILD = '''void draw(void) {
    f32 pos[2];
    Particle *p;
    if (paused == 0 && count < 100 && blocked == 0 && matrices < 0x80) {
        p = pool;
        pos[0] = p->x / 1.8f;
        pos[1] = -p->y / 1.8f;
        put(pos[0], pos[1]);
    }
}
'''


def children(module, source=BUILD):
    return [child for _, child in module.variants(source, 'draw')]


def test_the_leading_assignment_moves_above_the_last_test():
    first = children(guard_conjunct_hoist_split)[0]
    assert ('    if (paused == 0 && count < 100 && blocked == 0) {\n        p = pool;\n'
            '        if (matrices < 0x80) {\n            pos[0] = p->x / 1.8f;') in first
    assert len(children(guard_conjunct_hoist_split)) == 3


def test_a_local_read_later_or_by_the_moved_test_stays():
    read_after = BUILD.replace('    }\n}\n', '    }\n    use(p);\n}\n')
    assert not children(guard_conjunct_hoist_split, read_after)
    tested = BUILD.replace('matrices < 0x80', 'p != 0')
    assert not children(guard_conjunct_hoist_split, tested)
    faulting = BUILD.replace('p = pool;', 'p = head->next;')
    assert not children(guard_conjunct_hoist_split, faulting)
    either = BUILD.replace('blocked == 0 &&', 'blocked == 0 ||')
    assert not children(guard_conjunct_hoist_split, either)


def test_negation_moves_across_the_cast_and_back():
    cast = children(float_negation_cast_order)
    assert 'pos[1] = -(f32) p->y / 1.8f;' in cast[0]
    assert 'pos[1] = -p->y / 1.8f;' in children(float_negation_cast_order, cast[0])[0]
    assert not children(float_negation_cast_order, BUILD.replace('-p->y', 'p->x - p->y'))


def test_float_pair_grows_to_a_vector():
    assert 'f32 pos[3];' in children(float_pair_vec3)[0]
    assert not children(float_pair_vec3, BUILD.replace('put(pos[0], pos[1]);', 'put(pos);'))
