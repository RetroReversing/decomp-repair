"""Byte reads staged before a call, folded into its argument (a memcpy-like ROM write, 250 -> 100)."""
from decomprepair import registry
from decomprepair.call_load_temps_inline import FAMILY, variants

SOURCE = """s32 put(s32, s32, u8);

void copy(s32 dst, u8 *src, u32 size)
{
    u8 temp_v0;
    u8 temp_v1;
    s32 temp_a2;
    void *var_s3;

    var_s3 = src + 3;
    do {
        temp_a2 = (*(u8 *)((char *)(var_s3) + 0));
        temp_v0 = (*(u8 *)((char *)(var_s3) + -2));
        temp_v1 = (*(u8 *)((char *)(var_s3) + -1));
        { var_s3 += 4; }
        put(dst, (*src << 0x18) | (temp_v0 << 0x10) | (temp_v1 << 8) | temp_a2, temp_a2);
        dst += 4;
        src += 4;
        size -= 4;
    } while (size >= 4U);
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'copy') if family == FAMILY]


def test_the_reads_move_into_the_call_and_the_step_follows_it():
    dropped, kept = children()
    assert 'temp_' not in dropped and 's32 put(s32, s32);' in dropped
    assert ('put(dst, (*src << 0x18) | ((*(u8 *)((char *)(var_s3) + -2)) << 0x10) | '
            '((*(u8 *)((char *)(var_s3) + -1)) << 8) | (*(u8 *)((char *)(var_s3) + 0))); { var_s3 += 4; }') in dropped
    assert '| (*(u8 *)((char *)(var_s3) + 0)), (*(u8 *)((char *)(var_s3) + 0))); { var_s3 += 4; }' in kept
    assert 's32 put(s32, s32, u8);' in kept


def test_a_temporary_read_again_or_of_another_signedness_stays():
    again = SOURCE.replace('size -= 4;', 'size -= temp_v0;')
    assert all('temp_v0 = ' in child for child in children(again))
    signed = SOURCE.replace('    u8 temp_v1;', '    s8 temp_v1;')
    assert all('temp_v1 = ' in child for child in children(signed))


def test_a_pointer_the_call_names_or_that_the_callee_could_see_does_not_move():
    named = SOURCE.replace('put(dst, (', 'put((s32) var_s3, (')
    assert not children(named)
    shared = SOURCE.replace('    void *var_s3;\n', '').replace('s32 put(', 'void *var_s3;\ns32 put(')
    assert not children(shared)
    taken = SOURCE.replace('var_s3 = src + 3;', 'var_s3 = src + 3;\n    keep(&var_s3);')
    assert not children(taken)


def test_a_call_among_the_arguments_keeps_the_reads_where_they_are():
    assert not children(SOURCE.replace('put(dst, (', 'put(next(dst), ('))


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())
