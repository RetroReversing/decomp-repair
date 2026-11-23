from decomprepair import registry
from decomprepair.zero_guard_u16_counter import FAMILY, REPAIR, variants

SOURCE = """s32 cast(Mesh *m, Obj *o) {
    u32 temp_v1;
    u32 flag;
    s32 var_s0;
    s32 var_s0_2;
    s32 best;
    best = -1;
    flag = o->flags & 0x400;
    if ((((s32) flag) == 0) && (o->kind & 0x200)) {
        temp_v1 = m->flags & 4;
        if (temp_v1 != 0) {
            var_s0 = 0;
            if (flag < ((u16) m->count)) {
                do {
                    if (hit(m, var_s0 & 0xFFFF)) {
                        best = var_s0 & 0xFFFF;
                    }
                    var_s0 += 1;
                } while (((u32) (var_s0 & 0xFFFF)) < ((u16) m->count));
            }
        } else {
            var_s0_2 = 0;
            if (temp_v1 < ((u16) m->count)) {
                do {
                    if (hit(m, var_s0_2 & 0xFFFF)) {
                        best = var_s0_2 & 0xFFFF;
                    }
                    var_s0_2 += 1;
                } while (((u32) (var_s0_2 & 0xFFFF)) < ((u16) m->count));
            }
        }
    }
    return best;
}
"""


def test_guard_on_a_known_zero_flag_becomes_the_u16_counter_test():
    children = dict(enumerate(child for family, child in variants(SOURCE, 'cast')))
    assert all(family == FAMILY for family, _ in variants(SOURCE, 'cast'))
    both = children[len(children) - 1]
    assert 'if (var_s0 < ((u16) m->count))' in both
    assert 'if (var_s0_2 < ((u16) m->count))' in both
    assert 'u16 var_s0;' in both and 'u16 var_s0_2;' in both
    assert '& 0xFFFF' not in both
    assert 'while (var_s0_2 < ((u16) m->count));' in both
    # the counter is set before its new test
    assert both.index('var_s0_2 = 0;') < both.index('if (var_s0_2 <')


def test_counter_store_inside_the_guard_moves_above_it():
    source = SOURCE.replace("""            var_s0 = 0;
            if (flag < ((u16) m->count)) {
                do {""", """            if (flag < ((u16) m->count)) {
                var_s0 = 0;
                do {""")
    child = variants(source, 'cast')[0][1]
    assert child.index('var_s0 = 0;') < child.index('if (var_s0 < ((u16) m->count))')


def test_else_if_guard_gets_a_block_with_its_store():
    source = SOURCE.replace("""        } else {
            var_s0_2 = 0;
            if (temp_v1 < ((u16) m->count)) {
                do {""", """        } else
            if (temp_v1 < ((u16) m->count)) {
                var_s0_2 = 0;
                do {""").replace("""                } while (((u32) (var_s0_2 & 0xFFFF)) < ((u16) m->count));
            }
        }
    }""", """                } while (((u32) (var_s0_2 & 0xFFFF)) < ((u16) m->count));
            }
    }""")
    child = [c for _, c in variants(source, 'cast') if 'var_s0_2 <' in c][0]
    compact = ' '.join(child.split())
    assert 'else { var_s0_2 = 0; if (var_s0_2 < ((u16) m->count))' in compact


def test_guard_on_a_register_not_known_zero_is_left_alone():
    source = SOURCE.replace('if (temp_v1 != 0) {', 'if (o->kind != 0) {')
    children = [c for _, c in variants(source, 'cast')]
    assert all('if (var_s0_2 <' not in c for c in children)


def test_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
