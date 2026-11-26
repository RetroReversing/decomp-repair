"""A list walk's exit that reads the global it started from again: `v = G; <walk of v>; v = G; if (v ...)`."""
from decomprepair import registry
from decomprepair.walk_exit_global_reload import FAMILY, variants

DRAFT = '''extern void *D_80117420;
extern void *D_80117424;

void *f(void) {
    void *var_v1;

    var_v1 = D_80117420;
    if (var_v1 != NULL) {
        do {
            var_v1 = M2C_FIELD(var_v1, void **, 0x48);
        } while (var_v1 != NULL);
    }
    if (var_v1 != NULL) {
        D_80117420 = M2C_FIELD(var_v1, void **, 0x48);
        D_80117424 = var_v1;
    }
    return var_v1;
}
'''
TWO_LOADS = 'lui $v1, %hi(D_80117420)\nlw $v1, %lo(D_80117420)($v1)\nlui $v1, %hi(D_80117420)\nlw $v1, %lo(D_80117420)($v1)\n'
ONE_LOAD = 'lui $v1, %hi(D_80117420)\nlw $v1, %lo(D_80117420)($v1)\n'


def _kids(text, asm=None):
    return [s for fam, s in variants(text, 'f', asm) if fam == FAMILY]


def test_the_global_is_read_again_before_the_test_after_the_walk():
    want = DRAFT.replace('    }\n    if (var_v1 != NULL) {\n        D_80117420',
                         '    }\n    var_v1 = D_80117420;\n    if (var_v1 != NULL) {\n        D_80117420')
    assert want != DRAFT
    assert _kids(DRAFT, TWO_LOADS) == [want]
    assert _kids(DRAFT) == [want]          # no assembly: not checked


def test_only_when_the_target_loads_the_global_more_often_than_the_source_reads_it():
    assert _kids(DRAFT, ONE_LOAD) == []


def test_a_while_walk_without_an_enclosing_if():
    text = DRAFT.replace('    if (var_v1 != NULL) {\n        do {\n            var_v1 = M2C_FIELD(var_v1, void **, 0x48);\n'
                         '        } while (var_v1 != NULL);\n    }\n',
                         '    while (var_v1 != NULL) {\n        var_v1 = M2C_FIELD(var_v1, void **, 0x48);\n    }\n')
    kids = _kids(text, TWO_LOADS)
    assert len(kids) == 1 and '    }\n    var_v1 = D_80117420;\n    if (var_v1 != NULL) {' in kids[0]


def test_the_draft_itself_is_not_changed_twice():
    kids = _kids(DRAFT, TWO_LOADS)
    assert _kids(kids[0], TWO_LOADS) == []   # the reload is already there


def test_shapes_it_must_leave_alone():
    # no walk assigns the variable
    assert _kids(DRAFT.replace('var_v1 = M2C_FIELD(var_v1, void **, 0x48);', 'g(var_v1);'), TWO_LOADS) == []
    # a local of the same name as the "global"
    local = DRAFT.replace('    void *var_v1;\n', '    void *var_v1;\n    void *D_80117420;\n')
    assert _kids(local, TWO_LOADS) == []
    # the global is not declared outside the function
    assert _kids(DRAFT.replace('extern void *D_80117420;\n', ''), TWO_LOADS) == []
    # an `else` arm after the walk's if
    assert _kids(DRAFT.replace('        } while (var_v1 != NULL);\n    }\n', '        } while (var_v1 != NULL);\n    } else {\n        g();\n    }\n'),
                 TWO_LOADS) == []


def test_it_is_declared_for_the_registry():
    ours = [r for r in registry.declared() if FAMILY in r.families]
    assert len(ours) == 1 and registry.problems(ours[0]) == []
