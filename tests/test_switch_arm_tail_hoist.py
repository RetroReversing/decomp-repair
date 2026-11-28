from decomprepair import switch_arm_tail_hoist as hoist

ASM = '''
    beqz $v1, .L80000200
    slti $v0, $v1, 0x407
    addiu $v1, $v0, -0x1
    sltiu $v0, $v1, 0x419
    beqz $v0, .L80000200
    jr $v0
'''
SOURCE = '''void f(Ent *e) {
    s32 i;

    do {
        if (e->kind != 0) {
            switch (e->kind) {
            case 2:
                two(e);
                i += 1;
                break;
            case 100:
                other(e);
                i += 1;
                break;
            case 418:
                last(e);
                goto block_81;
            case 4: case 104: break; }
        } else {
block_81:
            i += 1;
        }
        e++;
    } while (i != 100);
}
'''


def test_the_shared_step_moves_after_the_if():
    (family, text), = hoist.variants(SOURCE, 'f', ASM)
    assert family == 'switch_arm_tail_hoist'
    assert text.count('i += 1;') == 1
    assert 'goto' not in text and 'block_81' not in text and 'else' not in text
    assert ' '.join(text.split()).endswith('case 4: case 104: break; } } i += 1; e++; } while (i != 100); }')


def test_it_needs_the_default_to_join_the_guard_in_the_target():
    assert hoist.variants(SOURCE, 'f', ASM.replace('beqz $v0, .L80000200', 'beqz $v0, .L80000300')) == []


def test_an_arm_without_the_step_stops_it():
    assert hoist.variants(SOURCE.replace('two(e);\n                i += 1;', 'two(e);'), 'f', ASM) == []
