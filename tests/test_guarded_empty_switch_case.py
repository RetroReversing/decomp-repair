from decomprepair import guarded_empty_switch_case as repair

ASM = '''sltiu $v0, $v1, 8
beqz $v0, .Lend
sll $v0, $v1, 2
lui $at, %hi(jtbl_80001000)
addu $at, $at, $v0
lw $v0, %lo(jtbl_80001000)($at)
jr $v0
nop
'''
SOURCE = '''void f(int x) {
    switch (x) {
    case 0: g(); break;
    case 1: h(); break;
    case 4: q(); break;
    }
}
'''


def test_a_target_guard_supplies_the_missing_last_empty_case():
    assert repair.bounds(ASM) == [8]
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1 and 'case 7: break;' in out[0][1]


def test_an_existing_default_gets_the_new_label():
    source = SOURCE.replace('    }\n}', '    default: q(); break;\n    }\n}')
    out = repair.variants(source, 'f', ASM)
    assert len(out) == 1 and 'case 7: default: q();' in out[0][1]


def test_only_a_complete_matching_guard_supports_the_rewrite():
    for asm in (ASM.replace('$v1, 2', '$a0, 2'), ASM.replace('jr $v0', 'jr $a0'),
                ASM.replace('beqz $v0', 'bnez $v0'), ASM.replace('addu $at', '.Lhere:\naddu $at'),
                ASM.replace('$v0, $v1, 8', '$v0, $v0, 8')):
        assert repair.variants(SOURCE, 'f', asm) == []
    assert repair.variants(SOURCE.replace('case 4:', 'case 7:'), 'f', ASM) == []


def test_relabels_outside_empty_case_into_a_missing_guarded_slot():
    source = SOURCE.replace('    }\n}', '    case 8: break;\n    }\n}')
    out = repair.variants(source, 'f', ASM)
    assert {v for _, v in out} == {source.replace('case 8:', f'case {n}:') for n in (2, 3, 5, 6, 7)}
    assert not repair.variants(source.replace('case 8: break;', 'case 8: g(); break;'), 'f', ASM)
    assert not repair.variants(source.replace('case 8: break;', 'case 8: break; default: g();'), 'f', ASM)
    assert not repair.variants(source.replace('case 8: break;', 'case 8: break; case 9: break;'), 'f', ASM)
