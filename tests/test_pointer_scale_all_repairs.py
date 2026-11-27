"""Every byte-step site in one child (a table slot read twice, both indexes scaled again by m2c)."""
from decomprepair import pointer_scale_all_repairs as p

TWICE = '''extern M2C_UNK D;
void f(void *arg0) {
    u16 *t;

    t = *((M2C_FIELD(arg0, u8 *, 0x6E) * 4) + &D);
    if (t != NULL) {
        M2C_FIELD(arg0, u16 *, 2) = (u16) M2C_FIELD(*((M2C_FIELD(arg0, u8 *, 0x6E) * 4) + &D), u16 *, 2);
    }
}
'''


def test_both_indexes_are_rewritten_in_one_child():
    (family, out), = p.variants(TWICE, 'f', 'sll        $v0, $v0, 2\n')
    assert family == 'pointer_byte_step_all'
    assert out.count('(&D)[M2C_FIELD(arg0, u8 *, 0x6E)]') == 2 and '+ &D' not in out


def test_one_site_is_left_to_pointer_byte_step():
    one = TWICE.replace('(u16) M2C_FIELD(*((M2C_FIELD(arg0, u8 *, 0x6E) * 4) + &D), u16 *, 2)', '0')
    assert p.variants(one, 'f', 'sll        $v0, $v0, 2\n') == []
    assert p.variants(TWICE, 'f', '') == []


def test_a_step_and_an_offset_together():
    source = 'void f(s32 *arg0) {\n    s32 *q;\n\n    q = arg0;\n    q += 4;\n    g(q + 4);\n}\n'
    (_, out), = p.variants(source, 'f', 'addiu      $v1, $v1, 4\n')
    assert 'q += 1;' in out and 'g((s8 *) q + 4);' in out
