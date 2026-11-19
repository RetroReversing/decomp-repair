"""Byte steps and offsets on typed pointers, as the target's immediates have them."""
from decomprepair import pointer_scale_repairs as p

STEP = '''void f(void) {
    u32 i;
    void **q;

    i = 0;
    q = &D;
    do {
        M2C_FIELD(*q, s32 *, 0x790) = 0;
        i += 1;
        q += 4;
    } while (i < 3U);
}
'''


def test_a_byte_step_on_a_typed_pointer():
    (family, out), = p.variants(STEP, 'f', 'addiu      $v1, $v1, 4\n')
    assert family == 'pointer_byte_step' and 'q += 1;' in out
    assert p.variants(STEP, 'f', 'addiu      $v1, $v1, 0x10\n') == []  # the target scaled it too


def test_a_byte_offset_on_a_typed_pointer():
    source = 'void f(void *arg0) {\n    M2C_UNK *t;\n\n    t = arg0;\n    g(t + 0x50);\n}\n'
    (_, out), = p.variants(source, 'f', 'addiu      $a1, $s1, 0x50\n')
    assert 'g((s8 *) t + 0x50);' in out


def test_an_index_into_a_word_symbol():
    source = 'extern s32 D;\nvoid f(u32 i, s32 v) {\n    *((i * 4) + &D) = v;\n}\n'
    (_, out), = p.variants(source, 'f', 'sll        $v0, $a0, 2\naddiu      $v0, $v0, 4\n')
    assert '(&D)[i] = v;' in out
