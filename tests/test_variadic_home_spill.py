"""A function written with a `...` tail, read as fixed or volatile parameters (a small N64 printf-like wrapper: 110 -> 0)."""
from decomprepair import registry
from decomprepair import variadic_home_spill as v

SPILLS = '''glabel func_8003E780
/* 3F380 8003E780 AFA40000 */  sw         $a0, 0x0($sp)
/* 3F384 8003E784 AFA50004 */  sw         $a1, 0x4($sp)
/* 3F388 8003E788 AFA60008 */  sw         $a2, 0x8($sp)
/* 3F38C 8003E78C AFA7000C */  sw         $a3, 0xC($sp)
/* 3F390 8003E790 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 3F394 8003E794 AFBF0010 */  sw         $ra, 0x10($sp)
'''
SOURCE = '''s32 func_800899DC();

void func_8003E780(volatile long long arg0, volatile int arg1, volatile int arg2, volatile int arg3) {
    func_800899DC();
}
'''


def test_a_wrapper_that_spills_from_a0_takes_one_named_parameter():
    (family, text), = v.variants(SOURCE, 'func_8003E780', SPILLS)
    assert family == 'variadic_home_spill'
    assert 'void func_8003E780(s32 arg0, ...) {\n    func_800899DC();\n}' in text
    assert 'volatile' not in text and text.startswith('s32 func_800899DC();')


def test_spills_from_a1_offer_two_named_parameters_and_one():
    asm = '\n'.join(l for l in SPILLS.splitlines() if '$a0' not in l)
    out = [t for _, t in v.variants(SOURCE.replace('long long', 's32'), 'func_8003E780', asm)]
    assert len(out) == 2
    assert 'func_8003E780(s32 arg0, int arg1, ...)' in out[0]
    assert 'func_8003E780(s32 arg0, ...)' in out[1]


def test_an_earlier_prototype_is_rewritten_and_a_call_is_not():
    source = ('void func_8003E780(s32, s32, s32, s32);\nvoid g(void) { func_8003E780(1, 2, 3, 4); }\n'
              + SOURCE.replace('volatile ', ''))
    (_, text), = v.variants(source, 'func_8003E780', SPILLS)
    assert text.startswith('void func_8003E780(s32, ...);\nvoid g(void) { func_8003E780(1, 2, 3, 4); }\n')
    (_, again), = v.variants(source.replace('(s32, s32, s32, s32);', '();'), 'func_8003E780', SPILLS)
    assert again.startswith('void func_8003E780(s32 arg0, ...);')


def test_left_alone_without_the_evidence():
    body_after_frame = SPILLS.replace('sw         $a0, 0x0($sp)', 'nop').replace('nop', 'addiu $sp, $sp, -0x18')
    assert v.variants(SOURCE, 'func_8003E780', body_after_frame) == []
    assert v.variants(SOURCE, 'func_8003E780', '') == []
    assert v.variants(SOURCE, 'func_8003E780', SPILLS.replace('0xC($sp)', '0x10($sp)')) == []  # wrong home slot
    assert v.variants(SOURCE, 'func_8003E780', 'sw $a3, 0xC($sp)\naddiu $sp, $sp, -0x18\n') == []  # only the last
    assert v.variants(SOURCE.replace('arg0, volatile', 'arg0, ..., volatile'), 'func_8003E780', SPILLS) == []


def test_a_body_that_reads_an_unnamed_parameter_is_left_alone():
    source = SOURCE.replace('func_800899DC();\n}', 'func_800899DC(arg1);\n}')
    assert v.variants(source, 'func_8003E780', SPILLS) == []


def test_it_declares_itself():
    assert any(r.module == 'variadic_home_spill' for r in registry.declared())
