"""Shapes from functions an N64 game's deep passes left unimproved: each family proposes the C that matched."""
from decomprepair import compare_tree_switch_repairs as tree
from decomprepair import leading_parameter_repairs as leading
from decomprepair import tail_shape_repairs as tail


def family(source, name, wanted):
    return [text for f, text in tail.variants(source, name) if f == wanted]


def test_negated_flag_return():
    source = '''s32 f(void *a, f32 x) {
    s32 var_v0;

    g(a);
    var_v0 = 1;
    if (!(h(a) < x)) {
        return 0;
    }
    return var_v0;
}
'''
    out, = family(source, 'f', 'negated_flag_return')
    assert '    if (h(a) < x) {\n        return 1;\n    }\n    return 0;\n}' in out and 'var_v0' not in out
    assert family(source.replace('return 0;\n    }', 'return 0;\n    }\n    k(var_v0);'), 'f', 'negated_flag_return') == []


def test_early_base_local():
    source = '''void f(void *arg0) {
    if (M2C_FIELD(M2C_FIELD(arg0, void **, 0x68), s8 *, 0xE) != 0) {
        goto block_8;
    }
    if ((M2C_FIELD(M2C_FIELD(arg0, void **, 0x6C), s32 *, 0x88) & 0x01E00000) == 0x600000) {
        goto block_8;
    }
    g(arg0, 0x208);
    return;
block_8:
    g(arg0, 0x209);
}
'''
    out, = family(source, 'f', 'early_base_local')
    assert '{\n    void *__repair_base = M2C_FIELD(arg0, void **, 0x6C);' in out
    assert '(M2C_FIELD(__repair_base, s32 *, 0x88) & 0x01E00000)' in out
    # the first test's own base isn't moved, and a parameter that changes isn't read early
    assert family(source.replace('    g(arg0, 0x208);', '    arg0 = h();\n    g(arg0, 0x208);'), 'f', 'early_base_local') == []


def test_hardware_register_store():
    source = '''extern s32 D_A4500000;
s32 f(s32 a) {
    D_A4500000 = g(a);
    *(volatile s32 *)0xA4500004 = a;
    return 0;
}
'''
    out, = family(source, 'f', 'hardware_register_store')
    assert '    *(volatile s32 *)0xA4500000 = g(a);' in out
    assert family(source.replace('D_A4500000', 'D_80100000'), 'f', 'hardware_register_store') == []


def test_used_before_set():
    source = '''void f(void *arg0, void *arg1, f32 arg2) {
    f32 temp_fv1;

    (*(f32 *)((char *)(arg1) + 0x34)) = (f32) (temp_fv1 + ((-g(arg0)) - temp_fv1) * arg2);
    temp_fv1 = (*(f32 *)((char *)(arg1) + 0x34));
}
'''
    out, = family(source, 'f', 'used_before_set')
    assert ('(f32) (((*(f32 *)((char *)(arg1) + 0x34))) + ((-g(arg0)) - ((*(f32 *)((char *)(arg1) + 0x34)))) * arg2);'
            in out)
    assert 'temp_fv1' not in out
    assert family(source.replace('    (*(f32', '    temp_fv1 = 0;\n    (*(f32'), 'f', 'used_before_set') == []


def test_compare_tree_switch():
    source = '''u16 f(s32 arg0, s32 arg1) {
    s32 t;

    t = arg0 & 0xFFFF;
    if (t != 0xA5) {
        if (t < 0xA6) {
            if (t != 0xA3) {
                return 1U;
            }
            return A[arg1];
        }
        if (t != 0xA6) {
            return 1U;
        }
        return B[arg1];
    }
    return C[arg1];
}
'''
    reversed_, as_written, ascending = (text for _, text in tree.variants(source, 'f'))
    assert ('    switch (t) {\n    case 0xA5:\n        return C[arg1];\n    case 0xA6:\n        return B[arg1];\n'
            '    case 0xA3:\n        return A[arg1];\n    }\n    return 1U;\n}') in reversed_
    assert as_written.index('case 0xA3') < as_written.index('case 0xA6') < as_written.index('case 0xA5')
    assert ascending.index('case 0xA3') < ascending.index('case 0xA5') < ascending.index('case 0xA6')
    # different defaults: not a switch m2c could have read
    assert tree.variants(source.replace('return 1U;\n            }\n            return A', 'return 2U;\n            }\n'
                                        '            return A'), 'f') == []


def test_leading_parameters():
    source = '''void *g(s32, s32, s32, s32, s32);

void *f(s32 arg2, s32 arg3, u16 arg4) {
    return g(arg2 & 0xFFFF, arg3 & 0xFFFF, (s32) arg4);
}
'''
    asm = 'addiu      $sp, $sp, -0x20\nlhu        $t0, 0x32($sp)\nandi       $a2, $a2, 0xFFFF\n'
    (family_, out), = leading.variants(source, 'f', asm)
    assert family_ == 'leading_parameters'
    assert 'void *f(s32 arg0, s32 arg1, u16 arg2, u16 arg3, u16 arg4) {' in out
    assert 'return g(arg0, arg1, arg2, arg3, arg4);' in out
    assert 'void *g(s32, s32, s32, s32, s32, s32, s32);' in out
    assert leading.variants(source.replace('s32 arg2,', 's32 arg0,').replace('arg2 &', 'arg0 &'), 'f', asm) == []


def test_leading_argument_of_an_indirect_zero_wrapper():
    source = """\
extern s32 (*callback)(s32);
void f(void) {
    callback(0);
}
"""
    asm = """\
glabel f
lui $v0, %hi(slot)
lw $v0, %lo(slot)($v0)
addiu $sp, $sp, -0x18
sw $ra, 0x10($sp)
jalr $v0
addu $a1, $zero, $zero
lw $ra, 0x10($sp)
jr $ra
addiu $sp, $sp, 0x18
endlabel f
"""
    [(family, fixed)] = leading.variants(source, 'f', asm)
    assert family == leading.FAMILY
    assert fixed == source.replace('(s32);', '(s32, s32);').replace('f(void)', 'f(s32 arg0)').replace('callback(0)', 'callback(arg0, 0)')
    assert not leading.variants(source, 'f', asm.replace('$a1', '$a0'))
    assert not leading.variants(source, 'f', asm.replace('jalr $v0', 'jalr $v1'))
    assert not leading.variants(source, 'f', asm.replace('jalr $v0', 'move $a0, $zero\njalr $v0'))
    assert not leading.variants(source.replace('callback(0);', 'if (ready) callback(0);'), 'f', asm)
