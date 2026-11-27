from decomprepair import goto_join_result_return, registry

DRAFT = """u32 add(s32 arg0, s32 kind) {
    u32 temp_a0;
    u32 temp_a3;
    u32 var_v0;

    if (gCount >= 0x100U) {
        return 0U;
    }
    temp_a3 = gCount;
    gCount = temp_a3 + 1;
    if (kind == 4) {
        gSize += 0x20;
        goto block_6;
    }
    var_v0 = temp_a3;
    if (kind == 8) {
        var_v0 = 0;
        temp_a0 = gBig + 1;
        gBig = temp_a0;
        if (temp_a0 < 0x54U) {
block_6:
            var_v0 = temp_a3;
        }
    }
    return var_v0;
}
"""

WANT = """u32 add(s32 arg0, s32 kind) {
    u32 temp_a0;
    u32 temp_a3;

    if (gCount >= 0x100U) {
        return 0U;
    }
    temp_a3 = gCount;
    gCount = temp_a3 + 1;
    if (kind == 4) {
        gSize += 0x20;
    } else if (kind == 8) {
        temp_a0 = gBig + 1;
        gBig = temp_a0;
        if (temp_a0 >= 0x54U) {
            return 0;
        }
    }
    return temp_a3;
}
"""


def test_the_preset_result_becomes_an_early_return():
    assert goto_join_result_return.variants(DRAFT, 'add') == [('goto_join_result_return', WANT)]


def test_two_guards_jumping_in_chain_as_else_ifs():
    draft = DRAFT.replace('    var_v0 = temp_a3;\n    if (kind == 8)', '''    if (kind == 5) {
        gSize += 1;
        goto block_6;
    }
    var_v0 = temp_a3;
    if (kind == 8)''')
    (family, text), = goto_join_result_return.variants(draft, 'add')
    assert '} else if (kind == 5) {' in text and '} else if (kind == 8) {' in text and 'goto' not in text


def test_refuses_when_the_meaning_could_change():
    for old, new in (
        ('    return var_v0;\n', '    gSize = var_v0;\n    return var_v0;\n'),  # the result is used elsewhere
        ('        var_v0 = 0;\n', '        var_v0 = gBig;\n'),                  # the failing value is not a literal
        ('if (temp_a0 < 0x54U)', 'if (temp_a3++ < 0x54U)'),                     # the test writes the saved value
        ('    u32 var_v0;', '    u8 var_v0;'),                                  # the result is narrower than the value
        ('    var_v0 = temp_a3;\n    if', '    var_v0 = temp_a3;\n    gSize = 1;\n    if'),
        ('        gSize += 0x20;\n        goto block_6;\n    }\n', '        goto block_6;\n    } else {\n    }\n'),
    ):
        assert old in DRAFT
        assert goto_join_result_return.variants(DRAFT.replace(old, new), 'add') == []


def test_declares_itself():
    assert any(entry.module == 'goto_join_result_return' for entry in registry.declared())
