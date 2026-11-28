"""m2c's search loop whose found node is worked on in the other arm (one step of a 5565 -> 0 object reset)."""
from decomprepair.goto_found_walk import FAMILY, variants

SOURCE = """void reset(Obj *obj)
{
    Obj *var_s0;

    if (obj->next == NULL) {
        build(obj);
    } else {
        var_s0 = obj->next;
        if (var_s0->kind != 3) {
loop_58:
            var_s0 = var_s0->next;
            if (var_s0 != NULL) {
                if (var_s0->kind == 3) {
                    goto block_60;
                }
                goto loop_58;
            }
        } else {
block_60:
            var_s0->state = 3;
            var_s0->timer = 0;
        }
    }
}
"""


def texts(source):
    found = variants(source, 'reset')
    assert all(family == FAMILY for family, _ in found)
    return [' '.join(text.split()) for _, text in found]


def test_walk_returns_when_nothing_follows():
    returning, jumping = texts(SOURCE)
    assert ('while (var_s0->kind != 3) { var_s0 = var_s0->next; if (var_s0 == NULL) { return; } } '
            'var_s0->state = 3; var_s0->timer = 0; } }') in returning
    assert 'goto block_60_done;' in jumping and 'block_60_done:;' in jumping


def test_code_after_the_search_keeps_the_label():
    only, = texts(SOURCE.replace('    }\n}\n', '    }\n    finish(obj);\n}\n'))
    assert 'goto block_60_done;' in only and 'return;' not in only


def test_declines_when_the_tests_differ():
    assert texts(SOURCE.replace('var_s0->kind == 3', 'var_s0->kind == 4')) == []
