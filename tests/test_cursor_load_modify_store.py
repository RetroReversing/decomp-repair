"""cursor_load_modify_store: `p = G++;` after a store, as a read before it, a step of the copy and a write-back."""
from decomprepair import cursor_load_modify_store as clms
from decomprepair import registry

NAME = 'func_80040000'
SOURCE = '''typedef struct { s32 w0; s32 w1; } CursorRec8;
extern CursorRec8 *D_80177E18;

void func_80040000(void *arg0, s32 arg1) {
    CursorRec8 *temp_t0;

    M2C_FIELD(arg0, s32 *, 0x10) = arg1;
    temp_t0 = D_80177E18++;
    temp_t0->w0 = 0xFA000000;
    temp_t0->w1 = arg1;
}
'''
ASM = '''
glabel func_80040000
    /* 0 */  lui        $v0, %hi(D_80177E18)
    /* 4 */  lw         $t0, %lo(D_80177E18)($v0)
    /* 8 */  sw         $a1, 0x10($a0)
    /* c */  addiu      $v1, $t0, 0x8
    /* 10 */  sw        $v1, %lo(D_80177E18)($v0)
    /* 14 */  lui       $t1, 0xFA00
    /* 18 */  sw        $t1, 0x0($t0)
    /* 1c */  jr        $ra
    /* 20 */   sw       $a1, 0x4($t0)
endlabel func_80040000
'''


def _children(source=SOURCE, asm=ASM, **kw):
    return clms.variants(source, NAME, asm=asm, **kw)


def test_the_target_reads_the_cursor_above_a_store_and_writes_it_back_below():
    assert clms.evidence(ASM) == {'D_80177E18'}
    assert _children(asm='') == []
    nostore = ASM.replace('/* 8 */  sw         $a1, 0x10($a0)', '/* 8 */  nop')
    assert clms.evidence(nostore) == set() and _children(asm=nostore) == []
    assert clms.evidence(ASM.replace('/* 4 */  lw         $t0, %lo(D_80177E18)($v0)', '/* 4 */  lw $t0, 0($v0)')) == set()


def test_the_read_moves_above_the_store_and_the_step_and_write_back_follow():
    family, text = _children()[0]
    assert family == clms.FAMILY
    assert 'CursorRec8 *D_80177E18_q;' in text
    assert 'D_80177E18_q = D_80177E18;\n    M2C_FIELD(arg0, s32 *, 0x10) = arg1;\n    temp_t0 = D_80177E18_q++;\n    D_80177E18 = D_80177E18_q;' in text
    assert 'temp_t0 = D_80177E18++' not in text


def test_two_stores_above_give_a_second_child():
    source = SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x10) = arg1;\n', '    M2C_FIELD(arg0, s32 *, 0x14) = 0;\n    M2C_FIELD(arg0, s32 *, 0x10) = arg1;\n')
    texts = [t for _, t in _children(source)]
    assert len(texts) == 2
    assert any('D_80177E18_q = D_80177E18;\n    M2C_FIELD(arg0, s32 *, 0x14) = 0;' in t for t in texts)


def test_declines_what_could_change_the_cursor_or_is_not_the_shape():
    assert _children(SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x10) = arg1;\n', '    foo(arg1);\n')) == []  # (a call may change it)
    assert _children(SOURCE.replace('M2C_FIELD(arg0, s32 *, 0x10) = arg1;', 'M2C_FIELD(arg0, s32 *, 0x10) = D_80177E18 == 0;')) == []
    assert _children(SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x10) = arg1;\n', '')) == []  # (nothing to read above)
    assert _children(SOURCE.replace('extern CursorRec8 *D_80177E18;\n', '')) == []  # (no declaration to take the type from)
    assert _children(SOURCE.replace('temp_t0 = D_80177E18++;', 'temp_t0 = D_80177E18;')) == []
    assert clms.variants(SOURCE.replace('extern CursorRec8 *D_80177E18;\n', ''), NAME, header='extern CursorRec8 *D_80177E18;', asm=ASM)


def test_registered_and_needs_the_assembly():
    found = {r.module: r for r in registry.declared()}['cursor_load_modify_store']
    assert set(found.families) == set(clms.FAMILIES) and 'asm' in found.needs
