"""Six shapes of an m2c draft of a menu screen, on made-up functions (no game's code)."""
from decomprepair import (
    address_indexed_global,
    float_register_variable_argument,
    global_command_run,
    pointer_scale_repairs,
    stack_value_run_array,
    strided_element_record,
    symbol_stack_block_copy,
    target_call_arity_repairs,
)
from decomprepair.asm_symbol_read_width import variants as read_width
from decomprepair.registry import declared

FLOATS = '''void draw(u8 *, s32, s32, s32, s32);
extern s32 D_80001000;

void menu(void) {
    s32 temp_fs0;

    temp_fs0 = D_80001000;
    draw(0, 1, 2, temp_fs0, 3);
    draw(0, 1, 2, (s32) temp_fs0, 4);
    draw(0, 1, 2, 0x3F800000, 5);
}
'''
FLOAT_ASM = '''lwc1       $fs0, %lo(D_80001000)($at)
mfc1       $a3, $fs0
jal        draw
addiu      $a1, $zero, 1
'''


def test_float_variable_word_and_literal_become_f32_together():
    [(_, child)] = float_register_variable_argument.variants(FLOATS, 'menu', FLOAT_ASM)
    assert 'void draw(u8 *, s32, s32, f32, s32);' in child
    assert 'extern f32 D_80001000;' in child
    assert '    f32 temp_fs0;' in child
    assert 'draw(0, 1, 2, temp_fs0, 4);' in child
    assert 'draw(0, 1, 2, 1.0f, 5);' in child


def test_a_variable_also_read_as_an_integer_keeps_its_type():
    assert float_register_variable_argument.variants(FLOATS.replace('4);', '4);\n    g(temp_fs0);'), 'menu',
                                                     FLOAT_ASM) == []
    assert float_register_variable_argument.variants(FLOATS, 'menu', 'jal draw\nnop\n') == []


RUN = '''extern void *gCursor;

void menu(void) {
    void *temp_t0;
    void *temp_v1;

    temp_v1 = gCursor + 8;
    M2C_FIELD(gCursor, s32 *, 4) = 0x22;
    temp_t0 = temp_v1 + 8;
    M2C_FIELD(gCursor, s32 *, 0) = 0x11;
    gCursor = temp_v1;
    gCursor = temp_t0;
    M2C_FIELD(gCursor, s32 *, 8) = 0x33;
    M2C_FIELD(temp_v1, s32 *, 4) = -1;
}
'''


def test_a_batched_command_run_is_one_packet_per_command():
    [(_, child)] = global_command_run.variants(RUN, 'menu')
    first = '{ __repair_cmd *_g = (*(__repair_cmd **) &gCursor)++; _g->w0 = 0x11; _g->w1 = (u32) (0x22); }'
    second = '{ __repair_cmd *_g = (*(__repair_cmd **) &gCursor)++; _g->w0 = 0x33; _g->w1 = (u32) (-1); }'
    assert child.index(first) < child.index(second)
    assert 'temp_v1' not in child and 'temp_t0' not in child


def test_a_run_with_a_missing_word_is_left():
    assert global_command_run.variants(RUN.replace('    M2C_FIELD(temp_v1, s32 *, 4) = -1;\n', ''), 'menu') == []


PAIR = '''void menu(void) {
    u8 sp88;
    u8 sp89;

    sp88 = 1;
    sp89 = 0;
    g((s32) sp88, (s32) sp89);
}
'''


def test_neighbouring_stack_bytes_the_target_stores_are_one_array():
    asm = 'sb $v0, 0x88($sp)\nsb $zero, 0x89($sp)\n'
    [(_, child)] = stack_value_run_array.variants(PAIR, 'menu', asm)
    assert 'u8 sp88[2];' in child and 'sp88[1] = 0;' in child and 'g((s32) sp88[0], (s32) sp88[1]);' in child
    assert stack_value_run_array.variants(PAIR, 'menu', 'sb $v0, 0x88($sp)\n') == []


ELEMENTS = '''extern u8 D_80001000;

void menu(void) {
    s32 i;

    for (i = 0; i < 4; i++) {
        pos(M2C_FIELD(((char *)(&D_80001000) + i * 0x48), s32 *, 0x40));
        text(((char *)(&D_80001000) + i * 0x48));
    }
}
'''


def test_byte_strided_elements_are_a_record_array():
    [(_, child)] = strided_element_record.variants(ELEMENTS, 'menu')
    assert 'char pad0[0x40];' in child and 's32 m40;' in child and 'char pad44[0x4];' in child
    assert 'pos(D_80001000[i].m40);' in child and 'text(((void *) &D_80001000[i]));' in child
    assert 'extern u8 D_80001000;' not in child


INDEXED = '''extern u8 **D_80001000;

void menu(s32 page) {
    first(D_80001000);
    list((&D_80001000)[page]);
}
'''


def test_a_global_indexed_through_its_address_is_an_array():
    [(_, child)] = address_indexed_global.variants(INDEXED, 'menu')
    assert 'extern u8 **D_80001000[];' in child
    assert 'first(D_80001000[0]);' in child and 'list(D_80001000[page]);' in child
    assert address_indexed_global.variants(INDEXED.replace('first(D_80001000)', 'first(&D_80001000)'), 'menu') == []


def test_a_step_on_a_pointer_to_pointers():
    source = 'void menu(void) {\n    u8 **p;\n\n    p = list;\n    p += 4;\n}\n'
    asm = 'addiu      $s2, $s2, 4\naddiu      $t1, $v1, 0x10\n'
    (_, child), = pointer_scale_repairs.variants(source, 'menu', asm)
    assert 'p += 1;' in child


def test_three_bytes_are_copied_as_a_block():
    source = '''extern M2C_UNK D_80001000;

void menu(void) {
    s8 sp50[3];

    sp50[0] = M2C_FIELD(&D_80001000, s8 *, 0);
    sp50[1] = M2C_FIELD(&D_80001000, s8 *, 1);
    sp50[2] = M2C_FIELD(&D_80001000, s8 *, 2);
    g(sp50);
}
'''
    [(_, child)] = symbol_stack_block_copy.variants(source, 'menu')
    assert '*(__repair_bytes3 *) sp50 = *(__repair_bytes3 *) &D_80001000;' in child
    assert 's8 sp50[3];' in child and 'typedef struct { signed char b[3]; } __repair_bytes3;' in child


def test_an_unknown_byte_table_read_as_words():
    source = '''extern M2C_UNK D_80001000;
extern s32 D_80001010;

void menu(void) {
    if (*(s32 *)(D_80001010 + (u8 *)&D_80001000) != 0) {
        g();
    }
}
'''
    asm = '''addiu      $a0, $v0, %lo(D_80001000)
addu       $v1, $v1, $a0
lbu        $v0, 0x0($v1)
'''
    children = [child for _, child in read_width(source, 'menu', asm)]
    assert any('extern u8 D_80001000[];' in child and 'D_80001000[D_80001010]' in child for child in children)


def test_an_added_global_argument_is_declared_too():
    source = 's32 f(void);\n\nvoid menu(void) {\n    f();\n}\n'
    asm = '''lui        $v0, %hi(gScore)
lw         $a0, %lo(gScore)($v0)
jal        f
nop
'''
    children = [child for _, child in target_call_arity_repairs.variants(source, 'menu', asm)]
    assert any('extern s32 gScore;' in child and 'f(gScore);' in child for child in children)


def test_the_new_modules_are_registered():
    families = {family for repair in declared() for family in repair.families}
    for module in (address_indexed_global, float_register_variable_argument, global_command_run,
                   stack_value_run_array, strided_element_record):
        assert module.FAMILY in families
