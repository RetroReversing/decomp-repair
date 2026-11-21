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


def test_share_measured_result_copy_at_the_exit():
    from decomprepair.shared_return_repairs import result_copy_variants

    source = """void f(void) {
    s32 flag;
    s32 result;
    flag = 0;
    if (obj != NULL) {
        result = flag;
        if (M2C_FIELD(obj, void **, 0x14) != NULL) {
            if (check(obj)) flag = 1;
            goto done;
        }
    } else {
done:
        result = flag;
    }
    if (result == 0) {
        fallback();
    }
}
"""
    rows = [
        (' ', 'beqz $v0, 0x40', 'beqz $v0, 0x40'),
        ('r', 'move $v0, $s3', 'move $v1, $zero'),
        (' ', 'nop', 'nop'),
        ('r', 'move $v0, $s3', 'move $v1, $s3'),
        ('r', 'bnez $v0, 0x50', 'bnez $v1, 0x50'),
    ]
    [(family, candidate)] = result_copy_variants(source, 'f', rows)
    assert family == 'shared_result_copy'
    assert '}\ndone:\n    result = flag;\n    if (result == 0)' in candidate
    assert 'goto done;' in candidate
    assert not result_copy_variants(source, 'f', rows[1:])
    assert not result_copy_variants(source, 'f', rows[:-1])
    assert not result_copy_variants(source.replace('goto done;', 'fallback();'), 'f', rows)
    assert not result_copy_variants(source.replace('s32 flag;', 'volatile s32 flag;'), 'f', rows)
