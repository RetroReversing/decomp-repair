from decomprepair import registry
from decomprepair import target_store_sequence as repair

P = '(*(s16 *)((char *)(gRec) + %s)) = %s;'
LINES = [P % ('0xC', 'v'), P % ('0xC', 'v'), '(*(s32 *)((char *)(gRec) + 0x14)) = 0x2E1;', P % ('0xC', 'v'),
         P % ('2', '0'), P % ('0', '0x1999'),
         '(*(s32 *)((char *)(gRec) + 0x18)) = (s32) ((*(s32 *)((char *)(gRec) + 0x18)) + 0x10);']
SOURCE = 'void play(s16 v) {\n    start();\n' + ''.join(f'    {line}\n' for line in LINES) + '    done();\n}\n'
ASM = '''
    sw         $ra, 0x14($sp)
    sh         $v1, 0xC($v0)
    sh         $v1, 0xC($v0)
    sh         $v1, 0xC($v0)
    sw         $v0, 0x14($v1)
    sh         $v0, 0x0($v1)
    sh         $zero, 0x2($v0)
    sw         $v0, 0x18($v1)
'''


def test_the_run_takes_the_targets_order_in_one_child():
    texts = [text for _, text in repair.variants(SOURCE, 'play', ASM)]
    wanted = [LINES[i] for i in (0, 1, 3, 2, 5, 4, 6)]
    assert texts == ['void play(s16 v) {\n    start();\n' + ''.join(f'    {line}\n' for line in wanted)
                     + '    done();\n}\n']


def test_member_macros_move_too():
    source = 'void f(void *p) {\n    M2C_FIELD(p, s32 *, 8) = 0;\n    M2C_FIELD(p, u8 *, 4) = 1;\n}\n'
    text = repair.variants(source, 'f', 'sb $v0, 0x4($a0)\nsw $zero, 0x8($a0)\n')[0][1]
    assert text.index('u8 *, 4') < text.index('s32 *, 8')


def test_runs_that_may_not_move_are_left():
    asm = 'sw $v0, 0x4($a0)\nsw $v0, 0x0($a0)\n'
    first = '    M2C_FIELD(p, s32 *, 0) = 1;\n'
    for second in ('    M2C_FIELD(p, s32 *, 4) = next();\n', '    M2C_FIELD(p, s32 *, 4) = n++;\n',
                   '    *(s32 *)((char *)(p) + 4) = *(s32 *)((char *)(p) + 0);\n',
                   '    M2C_FIELD(q, s32 *, 4) = 2;\n'):
        assert repair.variants('void f(void *p) {\n' + first + second + '}\n', 'f', asm) == []
    # the target already has the written order, or doesn't store those fields together
    done = 'void f(void *p) {\n    M2C_FIELD(p, s32 *, 4) = 2;\n    M2C_FIELD(p, s32 *, 0) = 1;\n}\n'
    assert repair.variants(done, 'f', asm) == []
    assert repair.variants(done, 'f', 'sw $v0, 0x0($a0)\nsw $v0, 0x8($a0)\n') == []


def test_it_declares_itself():
    entry = registry.get('target_store_sequence')
    assert entry and not registry.problems(entry)
