from decomprepair import (
    m2c_value_temporaries,
    m2c_word_table_draft,
    repeated_index_argument,
    word_low_byte_read,
    word_symbol_array_index,
)

ASM = 'addiu $v0, $zero, 0xff\nsb $v0, 0x10($s0)\nlbu $v0, 0x3($v0)\n'
DRAFT = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
typedef s32 M2C_UNK;
M2C_UNK report(void *, M2C_UNK *, s32, s32);
extern M2C_UNK D_80100000;
extern M2C_UNK D_80100100;
extern M2C_UNK D_80100200;
extern M2C_UNK D_80100300;

typedef struct {
    s8 tint;
    u8 slot;
    s8 icon;
    s32 seen;
    s32 total;
} Rec;

void f(void *arg0) {
    s32 temp_a1;
    s32 temp_v0;
    s32 temp_v1;
    u8 temp_t0;

    (((Rec *) arg0)->tint) = 0xFF;
    if ((((Rec *) arg0)->seen) == 0) {
        temp_v1 = *(((((Rec *) arg0)->slot) * 4) + &D_80100000);
        (((Rec *) arg0)->total) = temp_v1;
        if (temp_v1 == 1) {
            goto block_3;
        }
        goto block_4;
    }
    if ((((Rec *) arg0)->total) == 0) {
block_3:
        temp_t0 = (((Rec *) arg0)->slot);
        report(((((Rec *) arg0)->slot) * 0x32) + &D_80100300, &D_80100200, *(((*(s32 *)((temp_t0 * 4) + &D_80100000) - 1) * 4) + &D_80100100), (s32) (((Rec *) arg0)->slot));
    } else {
block_4:
        temp_a1 = (((Rec *) arg0)->slot) * 4;
        temp_v0 = (s32) *(((((Rec *) arg0)->slot) * 4) + &D_80100000);
        report(temp_a1 + &D_80100300, &D_80100200, temp_v0, 0);
    }
    (((Rec *) arg0)->icon) = (s8) (M2C_FIELD((((((Rec *) arg0)->slot) * 4) + &D_80100000), u8 *, 3) - 1);
}
'''


def test_the_word_tables_are_declared_and_indexed_and_the_others_written_in_bytes():
    family, text = word_symbol_array_index.variants(DRAFT, 'f')[0]
    assert family == 'word_symbol_array_index'
    assert 'extern s32 D_80100000[];' in text and 'extern s32 D_80100100[];' in text
    assert 'extern M2C_UNK D_80100300;' in text  # a stride of 0x32 is no word index
    assert 'temp_v1 = D_80100000[((Rec *) arg0)->slot];' in text
    assert 'D_80100100[D_80100000[temp_t0] - 1]' in text
    assert '(((((Rec *) arg0)->slot) * 0x32) + (u8 *)&D_80100300)' in text
    assert 'M2C_FIELD(&D_80100000[((Rec *) arg0)->slot], u8 *, 3)' in text


def test_a_call_keeps_its_parentheses_around_an_address():
    source = 'extern M2C_UNK D_80100000;\nvoid f(s32 i) {\n    use((i * 4) + &D_80100000);\n}\n'
    assert 'use(&D_80100000[i]);' in word_symbol_array_index.variants(source, 'f')[0][1]


def test_the_low_byte_is_the_word_narrowed_only_on_big_endian():
    source = ('extern s32 words[];\nvoid f(u8 *p, s32 i) {\n'
              '    *p = M2C_FIELD(&words[i], u8 *, 3);\n}\n')
    assert '*p = ((u8) words[i]);' in word_low_byte_read.variants(source, 'f', ASM, 'mips')[0][1]
    assert word_low_byte_read.variants(source, 'f', ASM, 'mipsel') == []
    assert word_low_byte_read.variants(source, 'f', 'lbu $v0, 0x0($v0)\n', 'mips') == []


def test_the_repeated_index_is_dropped_from_every_call_with_the_prototype():
    source = ('s32 show(void *, s32);\nvoid f(Rec *p) {\n    show(table + p->slot * 50, p->slot);\n'
              '    show(table + (p->slot) * 8, (s32) (p->slot));\n}\n')
    text = repeated_index_argument.variants(source, 'f')[0][1]
    assert 's32 show();' in text
    assert 'show(table + p->slot * 50);' in text and 'show(table + (p->slot) * 8);' in text
    assert repeated_index_argument.variants('s32 show(s32, s32);\nvoid f(s32 a, s32 b) {\n    show(a, b);\n}\n',
                                            'f') == []


def test_temporaries_are_written_out_and_a_stored_member_is_read_back():
    source = ('void f(Rec *p) {\n    s32 temp_v1;\n    s32 temp_a0;\n\n    temp_a0 = p->slot * 4;\n'
              '    temp_v1 = counts[temp_a0];\n    p->total = temp_v1;\n    if (temp_v1 == 1) {\n        one();\n    }\n}\n')
    found = dict(m2c_value_temporaries.variants(source, 'f'))
    assert 'p->total = counts[(p->slot * 4)];' in found['m2c_value_temporaries_readback']
    assert 'if (p->total == 1)' in found['m2c_value_temporaries_readback']
    assert 'if (counts[(p->slot * 4)] == 1)' in found['m2c_value_temporaries']
    assert 'temp_' not in found['m2c_value_temporaries']


def test_a_value_read_after_a_call_or_a_store_it_depends_on_stays():
    source = ('void f(Rec *p) {\n    s32 a;\n    s32 b;\n\n    a = p->total;\n    b = p->slot;\n    work();\n'
              '    p->total = 0;\n    use(a, b);\n}\n')
    assert m2c_value_temporaries.variants(source, 'f') == []


def test_the_composed_child_reaches_the_indexed_unjumped_form():
    family, text = m2c_word_table_draft.variants(DRAFT, 'f', ASM, 'mips')[0]
    assert family == 'm2c_word_table_draft'
    body = text[text.index('void f('):]
    assert 'goto' not in body and 'temp_' not in body
    assert 'u8 tint;' in text and 's8 icon;' in text
    assert 'M2C_UNK report();' in text
    assert '(u8) D_80100000[((Rec *) arg0)->slot]' in body
    assert '(((Rec *) arg0)->total) == 1' in body
