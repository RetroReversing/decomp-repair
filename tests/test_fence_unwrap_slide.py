from decomprepair.fence_unwrap_slide import FAMILY, variants

# the saved best of a KMC GCC 2.7.2 -O2 -fno-expensive-optimizations chunked transfer loop (an N64 game), shortened
SOURCE = """s32 func_80027F00();
s32 f(s32 arg0, s32 arg1, u32 arg2) {
    s32 temp_s5;
    s32 var_s2;
    u32 var_s1;

    var_s1 = arg2;
    /*__repair_loop_weight*/do { var_s2 = 0; } while (0);
    temp_s5 = func_80027F00();
    while (var_s1 != 0) {
        var_s2 += g(arg0, var_s1);
        var_s1 -= 1;
    }
    h(temp_s5);
    return var_s2;
}
"""

MATCHED = """    temp_s5 = func_80027F00();
    var_s2 = 0;
"""


def test_the_fence_opens_and_its_constant_slides_past_the_call_in_one_child():
    children = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert any(MATCHED in text for text in children)
    # every child opens the fence and none keeps the statement in its old place
    assert all('while (0)' not in text and '__repair_loop_weight' not in text for text in children)
    assert all('    var_s1 = arg2;\n    var_s2 = 0;\n    temp_s5' not in text for text in children)


def test_a_fence_around_a_call_or_a_block_is_not_opened():
    call = SOURCE.replace('do { var_s2 = 0; } while (0);', 'do { var_s2 = k(); } while (0);')
    assert variants(call, 'f') == []
    block = SOURCE.replace('do { var_s2 = 0; } while (0);', 'do { if (arg0) { var_s2 = 0; } } while (0);')
    assert variants(block, 'f') == []


def test_it_is_declared():
    from decomprepair.registry import declared
    assert any(FAMILY in r.families for r in declared())
