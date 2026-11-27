from decomprepair import copy_nested_goto_tail as repair

HEADER = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
SOURCE = '''void f(char *p, int x, int y) {
    if (x) {
        if (y) { h(); } else {
label:      M2C_FIELD(p, u8 *, 8) = 0U;
        }
    } else {
        if (y) { goto label; }
        h();
    }
    h();
}
'''


def test_copies_store_and_jumps_to_original_join():
    out = repair.variants(SOURCE, 'f', HEADER)
    assert len(out) == 1
    assert 'if (y) { M2C_FIELD(p, u8 *, 8) = 0U; goto decomp_tail_join; }' in out[0][1]
    assert 'decomp_tail_join: ;\n    h();' in out[0][1]


def test_refuses_other_code_after_store_or_nested_branch():
    assert not repair.variants(SOURCE.replace('= 0U;\n        }', '= 0U; h();\n        }'), 'f', HEADER)
    assert not repair.variants(SOURCE.replace('        }\n    } else', '        } h();\n    } else'), 'f', HEADER)
    assert not repair.variants(SOURCE.replace('if (y) { h(); } else', 'while (y) { h(); }'), 'f', HEADER)
    assert not repair.variants(SOURCE, 'f', '')
