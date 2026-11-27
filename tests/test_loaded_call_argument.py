"""loaded_call_argument: a dropped argument the target loads beside another argument's load gets that read."""
from decomprepair import loaded_call_argument as lca
from decomprepair import registry

SOURCE = '''s32 wrap();
s32 busy();
void * show();
extern s32 guard;
extern s16 index;
extern char table[];

void f(void) {
    if ((guard == 0) && (busy(2) == 0)) {
        show(*(s32 *)((index * 0x10) + table));
        *(s32 *)((index * 0x10) + table + 8) = wrap();
    }
}
'''
ASM = '''glabel f
/* 0 80001000 3C028007 */  lui        $v0, %hi(guard)
/* 4 80001004 8C42DF60 */  lw         $v0, %lo(guard)($v0)
/* 8 80001008 27BDFFE0 */  addiu      $sp, $sp, -0x20
/* C 8000100C AFBF0018 */  sw         $ra, 0x18($sp)
/* 10 80001010 14400017 */  bnez       $v0, .L80001070
/* 14 80001014 AFB00010 */   sw        $s0, 0x10($sp)
/* 18 80001018 0C01959D */  jal        busy
/* 1C 8000101C 24040002 */   addiu     $a0, $zero, 0x2
/* 20 80001020 14400013 */  bnez       $v0, .L80001070
/* 24 80001024 3C108010 */   lui       $s0, %hi(table)
/* 28 80001028 3C118007 */  lui        $s1, %hi(index)
/* 2C 8000102C 8622E0D4 */  lh         $v0, %lo(index)($s1)
/* 30 80001030 261090F0 */  addiu      $s0, $s0, %lo(table)
/* 34 80001034 00021100 */  sll        $v0, $v0, 4
/* 38 80001038 00501021 */  addu       $v0, $v0, $s0
/* 3C 8000103C 8C440000 */  lw         $a0, 0x0($v0)
/* 40 80001040 0C0196A4 */  jal        show
/* 44 80001044 00000000 */   nop
/* 48 80001048 8622E0D4 */  lh         $v0, %lo(index)($s1)
/* 4C 8000104C 00021100 */  sll        $v0, $v0, 4
/* 50 80001050 00501021 */  addu       $v0, $v0, $s0
/* 54 80001054 8C440004 */  lw         $a0, 0x4($v0)
/* 58 80001058 0C019464 */  jal        wrap
/* 5C 8000105C 00000000 */   nop
.L80001070:
/* 60 80001070 03E00008 */  jr         $ra
/* 64 80001074 27BD0020 */   addiu     $sp, $sp, 0x20
'''
READ = '*(s32 *)((u8 *)((index * 0x10) + table) + 0x4)'


def test_the_second_call_reads_beside_the_first_calls_argument():
    out = lca.variants(SOURCE, 'f', asm=ASM)
    assert out == [(lca.FAMILY, SOURCE.replace('wrap();\n    }', f'wrap({READ});\n    }}'))]


def test_a_void_declaration_gains_the_parameter():
    source = SOURCE.replace('s32 wrap();', 's32 wrap(void);')
    assert 's32 wrap(s32);' in lca.variants(source, 'f', asm=ASM)[0][1]


def test_a_register_read_by_something_else_is_no_argument():
    asm = ASM.replace('jal        wrap', 'sw         $a0, 0x8($v0)\n/* 0 0 0 */  jal        wrap')
    assert lca.variants(SOURCE, 'f', asm=asm) == []


def test_a_load_through_another_address_is_not_rendered():
    asm = ASM.replace('lw         $a0, 0x4($v0)', 'lw         $a0, 0x4($s1)')
    assert lca.variants(SOURCE, 'f', asm=asm) == []


def test_a_header_with_another_count_rules_the_callee_out():
    assert lca.variants(SOURCE, 'f', asm=ASM, header='s32 wrap(void);') == []


def test_the_family_declares_itself():
    assert any(item.module == 'loaded_call_argument' for item in registry.declared())
