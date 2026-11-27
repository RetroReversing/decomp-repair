"""A display-list draft whose cursor global stands for a value it no longer holds (a homemade routine)."""
from decomprepair import gbi_macro_commands, gbi_stale_draft, registry

DRAFT = """extern void *gCursor;

void draw_marks(s32 arg0, s32 arg1, u32 arg2) {
    s32 temp_a;
    s32 temp_b;
    s32 temp_c;
    s32 temp_d;
    s32 var_t1;
    s32 var_t1_2;
    u32 var_t2;
    u32 var_t2_2;
    void *temp_v0;
    void *temp_v1;
    void *temp_a0;
    void *temp_a1;
    void *temp_a2;

    var_t2 = 0;
    var_t1 = arg0;
    temp_v1 = gCursor + 8;
    M2C_FIELD(gCursor, s32 *, 0) = 0xE7000000;
    M2C_FIELD(gCursor, s32 *, 4) = 0;
    gCursor = temp_v1;
    gCursor = temp_v1 + 8;
    M2C_FIELD(gCursor, s32 *, 8) = 0xFA000000;
    M2C_FIELD(temp_v1, s32 *, 4) = 0x10203000;
    do {
        temp_a = var_t1 + 2;
        temp_b = var_t1 & 0x3FF;
        var_t1 += 5;
        var_t2 += 1;
        temp_a1 = gCursor;
        gCursor += 8;
        M2C_FIELD(temp_a1, s32 *, 0) = (s32) (((temp_a & 0x3FF) << 0xE) | ((((arg1 + 2) & 0x3FF) * 4) | 0xF6000000));
        M2C_FIELD(temp_a1, s32 *, 4) = (s32) ((temp_b << 0xE) | ((arg1 & 0x3FF) * 4));
    } while (var_t2 < 8U);
    var_t1_2 = arg0;
    var_t2_2 = 0;
    temp_a0 = gCursor;
    temp_a2 = gCursor + 8;
    M2C_FIELD(temp_a0, s32 *, 0) = 0xE7000000;
    gCursor = temp_a2;
    M2C_FIELD(temp_a0, s32 *, 4) = 0;
    if (arg2 != 0) {
        do {
            temp_c = var_t1_2 + 2;
            temp_d = var_t1_2 & 0x3FF;
            var_t1_2 += 5;
            var_t2_2 += 1;
            temp_v0 = gCursor;
            gCursor += 8;
            M2C_FIELD(temp_v0, s32 *, 0) = (s32) (((temp_c & 0x3FF) << 0xE) | ((((arg1 + 2) & 0x3FF) * 4) | 0xF6000000));
            M2C_FIELD(temp_v0, s32 *, 4) = (s32) ((temp_d << 0xE) | ((arg1 & 0x3FF) * 4));
        } while (var_t2_2 < arg2);
    }
}
"""


def children(family):
    return [text for found, text in gbi_stale_draft.variants(DRAFT, 'draw_marks') if found == family]


def body(text):
    return text[text.index('void draw_marks'):]


def test_stale_reads_become_one_command_each():
    child = body(children('gbi_stale_cursor')[0])
    assert 'M2C_FIELD' not in child
    assert child.count('gDPPipeSync(gCursor++);') == 2
    assert 'gDPSetPrimColor(gCursor++, 0, 0, 0x10, 0x20, 0x30, 0);' in child
    assert 'gDPFillRectangle(gCursor++, temp_b, arg1, temp_a, arg1 + 2);' in child
    assert 'gCursor += 8' not in child and 'gCursor = ' not in child


def test_loops_are_finished_in_one_child():
    child = body(children('gbi_stale_cursor_loops')[0])
    assert 'var_t1_2' not in child and 'var_t2_2' not in child
    assert child.count('arg1_copy = arg1;') == 2
    assert 'gDPFillRectangle(gCursor++, temp_d, arg1_copy, temp_c, arg1_copy + 2);' in child
    assert 'for (; var_t2 < arg2; var_t2++) {' in child and 'var_t2 += 1;\n        gDPFill' in child
    # the second loop's starting values follow the commands before its guard
    assert child.index('var_t1 = arg0;', child.index('while (var_t2 < 8U)')) > child.rindex('gDPPipeSync')


def test_compound_advance_is_never_read_through_a_local():
    source = ('extern void *gCursor;\nvoid f(void) {\n    void *p;\n    p = gCursor;\n    gCursor += 8;\n'
              '    M2C_FIELD(p, s32 *, 0) = 0;\n}\n')
    read = gbi_macro_commands._explicit_reads(source, 'f', 'gCursor', 'void')
    assert 'gCursor += 8;' in read and '_cur' not in read


def test_declared_and_quiet_without_a_cursor():
    assert any(repair.module == 'gbi_stale_draft' for repair in registry.declared())
    assert gbi_stale_draft.variants('void f(void) {\n    g();\n}\n', 'f') == []
