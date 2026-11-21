"""Equal constant returns written once, the others jumping to it."""
from decomprepair import shared_return_repairs as r

SOURCE = '''s32 f(s32 a) {
    if (a) {
        g(1);
        return 1;
    }
    h(0);
    return 1;
}
'''


def test_the_first_return_jumps_to_the_last():
    texts = [t for _, t in r.variants(SOURCE, 'f')]
    assert any('goto __shared_return_1;' in t and t.count('return 1;') == 1
               and t.index('goto __shared_return_1;') < t.index('__shared_return_1:') for t in texts)


def test_a_lone_return_is_left_alone():
    assert r.variants('s32 f(s32 a) {\n    return 1;\n}\n', 'f') == []


def test_guarded_global_return_has_an_early_zero_path():
    from decomprepair.shared_return_repairs import rewrite_global_guard

    asm = '''lui $v1, %hi(ready)
lw $v1, %lo(ready)($v1)
beqz $v1, .Ldone
addu $v0, $zero, $zero
lui $v0, %hi(queue)
lw $v0, %lo(queue)($v0)
.Ldone:
jr $ra
nop
'''
    source = '''s32 get_value(void) {
    s32 result;
    result = 0;
    if (ready != 0) {
        result = queue;
    }
    return result;
}
'''
    fixed = rewrite_global_guard(source, 'get_value', asm)
    assert fixed
    assert 'if (ready == 0) {\n        return 0;\n    }\n    return queue;' in fixed
    assert rewrite_global_guard(source, 'get_value', asm.replace('beqz', 'bnez')) is None
    assert rewrite_global_guard(source.replace('result = queue;', 'result = other;'), 'get_value', asm) is None
