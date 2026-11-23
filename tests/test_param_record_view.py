"""param_record_view: a `void *` parameter read through byte offsets, written as a record pointer."""
from decomprepair import param_record_view as prv
from decomprepair import registry

SOURCE = '''extern s32 D_80100000;
void helper(void *);

void f(void *arg0, s32 arg1) {
    D_80100000 = arg1;
    if ((*((u16 *) (((char *) arg0) + 4))) != 0) {
        *((s16 *) (((char *) arg0) + 0x18)) = (s16) (*((volatile u32 *) (((char *) arg0) + 0x34)));
    }
    *((f64 *) (((char *) arg0) + 8)) = 0.0;
    helper(arg0);
}
'''


def test_the_parameter_becomes_a_record_with_padding_and_members():
    [(family, text)] = prv.variants(SOURCE, 'f')
    assert family == prv.FAMILY
    assert 'void f(Rec_f_arg0 *arg0, s32 arg1)' in text
    assert text.index('typedef struct Rec_f_arg0') < text.index('void f(')
    assert 'u16 m4;' in text and 'f64 m8;' in text and 's16 m18;' in text and 'u32 m34;' in text
    assert 'u8 pad6[2];' in text  # the gap between m4 (2 bytes) and m8
    assert 'arg0->m4' in text and 'arg0->m18 =' in text
    assert '(*(volatile u32 *) &arg0->m34)' in text
    assert 'helper(arg0);' in text  # a bare argument stays


def test_two_types_at_one_offset_block_it():
    source = SOURCE.replace('(*((f64 *) (((char *) arg0) + 8)))', 'x').replace(
        '*((f64 *) (((char *) arg0) + 8)) = 0.0;', '*((f64 *) (((char *) arg0) + 8)) = 0.0; *((u32 *) (((char *) arg0) + 8)) = 0;')
    assert prv.variants(source, 'f') == []


def test_overlapping_members_block_it():
    source = SOURCE.replace('    helper(arg0);', '    *((u16 *) (((char *) arg0) + 0x36)) = 1;\n    helper(arg0);')
    assert prv.variants(source, 'f') == []


def test_a_misaligned_offset_blocks_it():
    assert prv.variants(SOURCE.replace('+ 8)', '+ 6)'), 'f') == []


def test_an_indexed_or_offset_use_blocks_it():
    source = SOURCE.replace('helper(arg0);', 'helper((char *) arg0 + 4);')
    assert prv.variants(source, 'f') == []


def test_it_declares_itself_to_the_registry():
    repair = registry.get('param_record_view')
    assert repair is not None and registry.problems(repair) == []
