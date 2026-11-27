"""The families one N64 model loader needed, on small homemade shapes."""
from decomprepair import (
    element_member_walk,
    helper_live_arguments,
    pointer_in_loop_counter,
    registry,
    scale_scratch_reuse,
    shift_store_interleave,
    step_into_both_arms,
    stored_field_local_value,
)

TYPES = """typedef struct { short x, s, t, pad; } Vert;
typedef struct { Vert v[3]; } Face;
typedef struct { unsigned char *data; unsigned char *nodes; unsigned short count, other; } Box;
extern void helper(void);
"""


def function(body):
    return TYPES + "void f(Box *obj, Face *tri, Vert *v, float *st, int w, int h) {\n" + body + "}\n"


def sq(text):
    return ' '.join(text.split())


def test_store_pairs_keep_both_stores():
    source = function("    v->s = st[0] * w; v->s <<= 6; v->t = st[1] * h; v->t <<= 6;\n")
    [(family, child)] = shift_store_interleave.variants(source, 'f')
    assert family == 'shift_store_interleave'
    assert ('repair_pair_a = st[0] * w; v->s = repair_pair_a; repair_pair_b = st[1] * h; v->t = repair_pair_b; '
            'v->s = repair_pair_a << 6; v->t = repair_pair_b << 6;') in child
    assert 'int repair_pair_a;' in child


def test_store_pairs_leave_dependent_values_alone():
    source = function("    v->s = w; v->s <<= 6; v->t = v->s; v->t <<= 6;\n")
    assert shift_store_interleave.variants(source, 'f') == []


def test_m2c_store_pairs_move_the_first_shift():
    source = function("    s32 a;\n    s32 b;\n"
                      "    v->s = (s16) a;\n    v->s = (s16) (a << 6);\n    b = h;\n    v->t = (s16) b;\n"
                      "    v->t = (s16) (b << 6);\n")
    [(_, child)] = shift_store_interleave.variants(source, 'f')
    assert 'v->s = (s16) a; b = h; v->t = (s16) b; v->s = (s16) (a << 6); v->t = (s16) (b << 6);' in sq(child)


def test_scaled_count_shares_the_byte_test_scratch():
    source = function("    int off;\n    if (obj->data[0] == 'M') {\n        w = 1;\n    }\n"
                      "    off = obj->count * 0x10;\n    obj->nodes += off;\n")
    children = [child for _, child in scale_scratch_reuse.variants(source, 'f')]
    assert any("off = obj->data[0];\n    if (off == 'M')" in c and 'off = obj->count;\n    off <<= 4;' in c
               for c in children)


def test_scaled_count_skips_a_live_local():
    source = function("    int off;\n    off = h;\n    if (obj->data[0] == 'M') {\n        w = off;\n    }\n"
                      "    off = obj->count * 0x10;\n    obj->nodes += off;\n")
    assert not any('off = obj->data[0];' in c for _, c in scale_scratch_reuse.variants(source, 'f'))


def test_helper_receives_computed_pointers():
    source = function("    unsigned char *a;\n    unsigned char *b;\n    unsigned char *c;\n"
                      "    a = obj->data + 4;\n    b = a + 8;\n    c = b + 12;\n    helper();\n")
    children = [c for _, c in helper_live_arguments.variants(source, 'f', 'mips')]
    assert any('helper(c, b, a);' in c and 'extern void helper();' in c for c in children)
    assert helper_live_arguments.variants(source, 'f', 'ppc') == []


def test_indexed_member_loop_walks_a_pointer():
    source = function("    int m;\n    for (m = 0; m < 3; m++) {\n"
                      "        if (w < tri->v[m].s || h < tri->v[m].t) {\n            break;\n        }\n    }\n")
    [(_, child)] = element_member_walk.variants(source, 'f')
    assert 'Vert *repair_walk;' in child
    assert 'repair_walk = &tri->v[0];' in child
    assert 'm++, repair_walk++)' in child
    assert 'w < repair_walk->s || h < repair_walk->t' in child


def test_counter_used_elsewhere_stays_indexed():
    source = function("    int m;\n    for (m = 0; m < 3; m++) {\n        w += tri->v[m].s + m;\n    }\n")
    assert element_member_walk.variants(source, 'f') == []


def test_step_moves_into_both_arms():
    source = function("    tri++;\n    if (w) {\n        h = 1;\n    } else {\n        h = 2;\n    }\n")
    [(_, child)] = step_into_both_arms.variants(source, 'f')
    assert 'if (w) { tri++; h = 1; } else { tri++; h = 2; }' in sq(child)
    assert step_into_both_arms.variants(source.replace('if (w)', 'if (tri)'), 'f') == []


def test_stored_field_read_uses_the_local():
    source = function("    unsigned char *nodes;\n    unsigned char *node;\n"
                      "    obj->nodes = nodes = obj->data + 4;\n    obj->count = 1;\n"
                      "    if (obj->count) {\n        helper();\n        node = obj->nodes;\n    } else {\n"
                      "        node = obj->nodes;\n    }\n")
    children = [c for _, c in stored_field_local_value.variants(source, 'f')]
    assert any('} else {\n        node = nodes;' in c for c in children)


def test_the_families_are_declared():
    declared = str(registry.declared())
    for module in (shift_store_interleave, scale_scratch_reuse, helper_live_arguments, element_member_walk,
                   step_into_both_arms, stored_field_local_value, pointer_in_loop_counter):
        assert module.FAMILY in declared


def test_a_pointer_rides_in_the_later_counter():
    source = function("    unsigned char *entry;\n    int m;\n    entry = obj->data + 4;\n"
                      "    obj->count = entry[0];\n    w = entry[1];\n    for (m = 0; m < 3; m++) {\n        h = m;\n    }\n")
    [(_, child)] = pointer_in_loop_counter.variants(source, 'f', 'mips')
    assert 'm = (u32) (obj->data + 4);' in child
    assert 'obj->count = ((unsigned char *) m)[0];' in child
    assert 'unsigned char *entry;' not in child
    late = source.replace("        h = m;\n", "        h = entry[m];\n")
    assert pointer_in_loop_counter.variants(late, 'f', 'mips') == []
