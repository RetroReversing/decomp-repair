"""A function m2c read with fixed parameters that the game wrote with `...`; a narrower raw store."""
from decomprepair import varargs_signature_repairs as v

SOURCE = '''void f(void *arg0, s32 arg1, s32 arg2, s32 arg3) {
    s32 temp_v0;

    if (arg0 != NULL) {
        temp_v0 = g(h(arg0), arg1, &arg2);
        if (temp_v0 >= 0) {
            *(s32 *)(h(arg0) + temp_v0) = 0;
        }
    }
}
'''
ASM = '''sw         $a1, 0x4($sp)
sw         $a2, 0x8($sp)
sw         $a3, 0xC($sp)
addiu      $sp, $sp, -0x20
sb         $zero, 0x0($v0)
'''


def test_varargs_then_the_byte_store():
    # An N64 function at 72.3%: 94.9% as varargs, exact with the byte store too.
    out = dict((family, text) for family, text in v.variants(SOURCE, 'f', ASM))
    varargs = out['varargs_signature']
    assert varargs.startswith('void f(void *arg0, s32 arg1, ...) {\n    char *__repair_ap;\n')
    assert ('        __repair_ap = (char *) __builtin_next_arg(arg1);\n'
            '        temp_v0 = g(h(arg0), arg1, __repair_ap);\n') in varargs
    assert '*(s8 *)(h(arg0) + temp_v0) = 0;' in out['raw_store_width']


def test_left_alone_otherwise():
    assert [f for f, _ in v.variants(SOURCE, 'f', ASM.replace('sw         $a', 'sw         $s'))] == ['raw_store_width']
    assert [f for f, _ in v.variants(SOURCE.replace('&arg2', 'arg2'), 'f', ASM)] == ['raw_store_width']
    assert v.variants(SOURCE, 'f', '') == []
    assert v.variants(SOURCE.replace(' = 0;', ' == 0;'), 'f', 'sb         $zero, 0x0($v0)\n') == []  # a load, not a store
