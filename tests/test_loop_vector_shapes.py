"""Loop and vector-update shapes measured on KMC gcc 2.7.2: proposals only, never compiled here."""
from decomprepair.loop_vector_shapes import variants

LOOP = '''void f(Obj *obj, Bone *bones) {
    s32 k;
    Bone *bone;
    for (k = 0, bone = bones; bone->idx >= 0; k++, bone++) {
        obj->out[k] = bone->a;
    }
}
'''


def _family(text, family, name='f'):
    return [src for fam, src in variants(text, name) if fam == family]


def test_walked_pointer_loop_becomes_indexed():
    [src] = _family(LOOP, 'indexed_pointer_loop')
    assert 'for (k = 0; bones[k].idx >= 0; k++) {\n        bone = &bones[k];' in src
    assert 'bone++' not in src


def test_walked_pointer_advanced_in_body_is_left_alone():
    text = LOOP.replace('obj->out[k] = bone->a;', 'obj->out[k] = bone->a;\n        bone++;')
    assert not _family(text, 'indexed_pointer_loop')


def test_read_only_local_pointer_gets_const():
    srcs = _family(LOOP, 'const_walked_pointer')
    assert srcs and '    const Bone *bone;' in srcs[0]


def test_pointer_written_through_or_passed_is_not_const():
    written = LOOP.replace('obj->out[k] = bone->a;', 'bone->a = 0;')
    passed = LOOP.replace('obj->out[k] = bone->a;', 'use(bone->a, bone);')
    assert not _family(written, 'const_walked_pointer')
    assert not _family(passed, 'const_walked_pointer')


VEC = '''void g(Mtx *m, Mtx *pm) {
    m->t.x += pm->t.x;
    m->t.y += pm->t.y;
    m->t.z += pm->t.z;
}
'''


def test_vector_compound_updates_become_sums_then_stores():
    first, second = _family(VEC, 'vector_update_temps', 'g')
    assert '__typeof__(m->t.x) vx_ = m->t.x + (pm->t.x);' in first
    assert first.index('vz_ = ') < first.index('m->t.x = vx_;')
    assert 'vx_t = pm->t.x;' in second


def test_vector_update_reading_itself_is_left_alone():
    text = VEC.replace('m->t.y += pm->t.y;', 'm->t.y += m->t.x;')
    assert not _family(text, 'vector_update_temps', 'g')


def test_other_processors_get_nothing():
    assert variants(LOOP, 'f', 'x86') == []


def test_values_read_through_the_pointer_may_be_call_arguments():
    text = LOOP.replace('obj->out[k] = bone->a;', 'use(bone->a.x, bone->b);')
    assert any('const Bone *bone;' in s for s in _family(text, 'const_walked_pointer'))


def test_a_table_and_its_walkers_go_const_together():
    text = LOOP.replace('    Bone *bone;\n', '    Bone *bone;\n    Bone *top;\n    u32 *frame;\n').replace(
        'obj->out[k] = bone->a;', 'obj->out[k] = bone->a + top->a + frame[k];')
    srcs = _family(text, 'const_walked_pointer')
    assert 'const Bone *bone;\n    const Bone *top;\n    u32 *frame;' in srcs[0]
