"""cursor_record_postfix: `p = G; G += K;` on an untyped global cursor, rewritten as `p = G++;` on a pointer to a K-byte record."""
from decomprepair import cursor_record_postfix as crp
from decomprepair import registry

NAME = 'func_80027060'
SOURCE = '''extern void *D_80177E18;

void func_80027060(s32 arg0, s32 arg1) {
    void *temp_t0;

    temp_t0 = D_80177E18;
    D_80177E18 += 8;
    M2C_FIELD(temp_t0, s32 *, 0) = 0xFA000000;
    M2C_FIELD(temp_t0, s32 *, 4) = (s32) ((arg0 << 0x18) | (arg1 & 0xFF));
}
'''


def _children(source=SOURCE, **kw):
    return crp.variants(source, NAME, **kw)


def test_the_cursor_becomes_a_typed_record_pointer_stepped_in_the_initialiser():
    postfix = dict(_children())[crp.FAMILY]
    assert 'typedef struct { s32 w0; s32 w1; } CursorRec8;' in postfix
    assert 'extern CursorRec8 *D_80177E18;' in postfix and 'CursorRec8 *temp_t0;' in postfix
    assert 'temp_t0 = D_80177E18++;' in postfix and 'D_80177E18 += 8' not in postfix
    assert 'temp_t0->w0 = 0xFA000000;' in postfix and 'temp_t0->w1 = (s32)' in postfix and 'M2C_FIELD' not in postfix


def test_the_view_child_keeps_two_statements_with_a_record_step():
    view = dict(_children())[crp.VIEW_FAMILY]
    assert 'temp_t0 = D_80177E18;\n    D_80177E18 += 1;' in view and 'temp_t0->w1' in view


def test_other_spellings_of_the_step_and_the_access():
    for step in ('D_80177E18 = D_80177E18 + 8;', 'D_80177E18 = (void *) (temp_t0 + 8);', 'D_80177E18 = temp_t0 + 0x8;'):
        children = _children(SOURCE.replace('D_80177E18 += 8;', step))
        assert children and 'temp_t0 = D_80177E18++;' in dict(children)[crp.FAMILY], step
    cast = SOURCE.replace('M2C_FIELD(temp_t0, s32 *, 4)', '*(s32 *)((u8 *)temp_t0 + 4)').replace(
        'M2C_FIELD(temp_t0, s32 *, 0)', '((u32 *) temp_t0)[0]')
    postfix = dict(_children(cast))[crp.FAMILY]
    assert 'w0; s32 w1;' in postfix.replace('u32 w0', 'w0') and 'temp_t0->w0 = 0xFA000000;' in postfix and 'temp_t0->w1 =' in postfix


def test_other_record_sizes_and_unwritten_words_and_floats():
    wide = SOURCE.replace('+= 8', '+= 16')
    assert 'typedef struct { s32 w0; s32 w1; u32 w2; u32 w3; } CursorRec16;' in dict(_children(wide))[crp.FAMILY]
    single = SOURCE.replace('+= 8', '+= 4').replace('    M2C_FIELD(temp_t0, s32 *, 4) = (s32) ((arg0 << 0x18) | (arg1 & 0xFF));\n', '')
    assert 'typedef struct { s32 w0; } CursorRec4;' in dict(_children(single))[crp.FAMILY]
    floats = SOURCE.replace('M2C_FIELD(temp_t0, s32 *, 4) = (s32) (', 'M2C_FIELD(temp_t0, f32 *, 4) = (f32) (')
    assert 'typedef struct { s32 w0; f32 w1; } CursorRec8;' in dict(_children(floats))[crp.FAMILY]


def test_several_pairs_one_global_and_an_integer_global():
    two = SOURCE.replace('    M2C_FIELD(temp_t0, s32 *, 4)', '    temp_t1 = D_80177E18;\n    D_80177E18 += 8;\n    M2C_FIELD(temp_t1, s32 *, 0) = 1;\n'
                         '    M2C_FIELD(temp_t0, s32 *, 4)').replace('void *temp_t0;', 'void *temp_t0;\n    void *temp_t1;')
    postfix = dict(_children(two))[crp.FAMILY]
    assert postfix.count('= D_80177E18++;') == 2 and 'temp_t1->w0 = 1;' in postfix and 'CursorRec8 *temp_t1;' in postfix
    word = SOURCE.replace('extern void *D_80177E18', 'extern s32 D_80177E18').replace('void *temp_t0', 's32 temp_t0')
    assert 'extern CursorRec8 *D_80177E18;' in dict(_children(word))[crp.FAMILY]


def test_declines_what_is_not_the_shape():
    assert _children(header='extern void *D_80177E18;') == []  # (a header type is shared: no local redeclaration)
    assert _children(SOURCE.replace('+= 8', '+= 6')) == [] and _children(SOURCE.replace('+= 8', '+= 36')) == []
    assert _children(SOURCE.replace('    D_80177E18 += 8;\n', '    D_80177E18 += 8;\n    foo(D_80177E18);\n')) == []  # (G read again)
    assert _children(SOURCE.replace('M2C_FIELD(temp_t0, s32 *, 4)', 'M2C_FIELD(temp_t0, s16 *, 4)')) == []
    assert _children(SOURCE.replace('M2C_FIELD(temp_t0, s32 *, 4)', 'M2C_FIELD(temp_t0, s32 *, 8)')) == []  # (outside the record)
    assert _children(SOURCE.replace('    M2C_FIELD(temp_t0, s32 *, 0)', '    bar(temp_t0);\n    M2C_FIELD(temp_t0, s32 *, 0)')) == []
    assert _children(SOURCE + 'void other(void) { D_80177E18 = 0; }\n') == []  # (another function names it)
    assert _children(SOURCE.replace('    D_80177E18 += 8;\n', '    foo();\n    D_80177E18 += 8;\n')) == []  # (not adjacent)


def test_a_type_name_already_taken_is_not_reused():
    assert 'CursorRec8_ ' in dict(_children('typedef int CursorRec8;\n' + SOURCE))[crp.FAMILY]


def test_registered_and_bounded():
    assert crp.REPAIR['variants'] is crp.variants and set(crp.FAMILIES) == {crp.FAMILY, crp.VIEW_FAMILY}
    assert len(_children()) <= crp.MAX_CHILDREN
    assert 'cursor_record_postfix' in {item.module for item in registry.declared()}
