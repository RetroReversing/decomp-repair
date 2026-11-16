"""Indexed copies retain typed accesses and qualify only evidenced private words."""
import re

import pytest

from decomprepair import indexed_record_repairs as repair
from decomprepair.indexed_record_support import Records, indexed_bases

HEADER = '''typedef unsigned char u8; typedef unsigned short u16;
typedef unsigned int u32; typedef int s32; typedef float f32;'''
SOURCE = '''
typedef struct Packet { u32 ticks; u8 state; char label[3]; u8 rate; u8 mode; u8 zero; u8 pad[5]; } Packet;
typedef struct Sample { u32 clock; u32 state; } Sample;
typedef struct Input { char code[8]; Sample rows[2]; u32 total; u32 control; } Input;
typedef struct Block { Packet entries[4]; u32 totals[4]; } Block;
extern Packet D_80400000[];
extern Block *table[];
extern u8 D_80300000;
extern u32 scale;
#define MEASURE(n,t) (fraction = (f32)(t), (u32)(((f32)(u32)((n) * scale) * 2.5f) / fraction))
void update(Input *input) {
    char code[8];
    u16 first, second, index, j;
    f32 fraction;
    first = second = index = 0;
    read_code(code, input->code);
    switch (code[0]) {
    case 'Q':
        first = code[1] - '0';
        second = code[2] - '1';
        break;
    case 'P':
        second = code[6] - '1';
        index = 0;
        first = code[3] - '0';
        break;
    }
    {
        Block *block = table[first] + second;
        u16 slot = index;
        u8 count = D_80300000;
        block->totals[slot] = input->total;
        D_80300000 = count + 1;
        for (j = 0; j < 2; j++) {
            D_80400000[j].ticks = input->rows[j].clock;
            D_80400000[j].state = input->rows[j].state;
            D_80400000[j].rate = MEASURE(input->total, D_80400000[j].ticks);
            D_80400000[j].zero = 0;
            D_80400000[j].mode = input->control;
        }
        for (j = 0; j < 2; j++) {
            D_80400000[5 + j].ticks = input->rows[j].clock;
            D_80400000[5 + j].state = input->rows[j].state;
            D_80400000[5 + j].rate = MEASURE(input->total, D_80400000[5 + j].ticks);
            D_80400000[5 + j].zero = 0;
            D_80400000[5 + j].mode = input->control;
        }
    }
}
'''


def assembly():
    words = []
    for offset in (0, 0x50):
        words += [(0x3C018040, 'lui $at, 0x8040'), (0x00300821, 'addu $at, $at, $s0'),
                  (0xAC220000 | offset, 'sw $v0, 0($at)'), (0x3C038040, 'lui $v1, 0x8040'),
                  (0x00701821, 'addu $v1, $v1, $s0'), (0x8C630000 | offset, 'lw $v1, 0($v1)'),
                  (0x46800021, 'cvt.d.w $f0, $f0')]
    words += [(0x3C038030, 'lui $v1, 0x8030'), (0x90630000, 'lbu $v1, 0($v1)')]
    return '\n'.join(f'/* {i*4:X} {0x80001000+i*4:08X} {word:08X} */ {text}' for i, (word, text) in enumerate(words))


def variants(function, source=SOURCE, asm=None, arch='mips', header=HEADER):
    return function(source, 'update', header, arch, assembly() if asm is None else asm)


def test_nested_declared_accesses_keep_qualifiers_on_the_affected_field_only():
    source = SOURCE.replace('u32 ticks;', 'volatile u32 ticks;')
    model = Records(source, 'update', HEADER)
    assert model.access('D_80400000[j].ticks').volatile
    assert not model.access('D_80400000[j].zero').volatile
    assert model.access('block->entries[index].mode').offset == 9
    assert model.access('input->rows[j].clock').size == 4
    assert model.access('input->rows[next()].clock') is None
    assert model.access('unknown[j].mode') is None
    assert variants(repair.store_orders, source)


def test_subarray_anchors_need_raw_target_evidence_and_a_declared_record_stride():
    proposals = variants(repair.rebase)
    assert len(proposals) == 1
    candidate = proposals[0][1]
    assert 'extern Packet D_80400050[];' in candidate
    assert 'D_80400050[j].ticks' in candidate
    assert 'D_80400000[j].ticks' in candidate
    assert not variants(repair.rebase, asm='lui $at, %hi(D_80400050)')
    assert not variants(repair.rebase, SOURCE.replace('D_80400000[]', 'D_80400000[32]'))
    assert not variants(repair.rebase, SOURCE.replace('5 + j', 'next() + j'))
    assert not variants(repair.rebase, arch='x86')
    assert 0x80400050 in indexed_bases(assembly())
    assert 0x80400050 not in indexed_bases(assembly().replace('00300821', '00000821').replace('00701821', '00001821'))


def test_record_word_capture_preserves_both_copies_and_scalar_conversion_order():
    candidate = variants(repair.word_captures)[0][1]
    assert 'volatile u32 ticks;' in candidate
    assert 'u32 __repair_record_word;' in candidate
    assert 'u8 state;' in candidate and 'volatile u8 state;' not in candidate
    assert candidate.count('__repair_record_word = D_80400000[') == 2
    assert candidate.count('fraction = (f32)__repair_record_word;') == 2
    assert 'MEASURE(input->total,' not in candidate
    assert '2.5f' in candidate
    for start in re.finditer(r'__repair_record_word = D_80400000', candidate):
        region = candidate[start.start():candidate.index('.rate =', start.start())]
        assert region.index('.state =') < region.index('fraction =')
    assert not variants(repair.word_captures, asm=assembly().replace('8C63', 'AC63'))
    assert not variants(repair.word_captures, SOURCE.replace('u8 state;', 'volatile u8 state;'))
    assert not variants(repair.word_captures, SOURCE.replace('input->total,', 'next(),'))
    assert not variants(repair.word_captures, SOURCE.replace('* 2.5f', '* next()'))
    assert not variants(repair.word_captures, SOURCE.replace('(n) * scale', '(n) * (n)'))


def test_ordinary_store_orders_remain_available_beside_volatile_words_but_reject_dependencies():
    source = SOURCE.replace('u32 ticks;', 'volatile u32 ticks;')
    candidates = variants(repair.store_orders, source)
    assert candidates
    assert any('mode = input->control;\n            D_80400000[j].zero = 0;' in c for _, c in candidates)
    assert not variants(repair.store_orders, source.replace('u8 zero;', 'volatile u8 zero;'))
    assert not variants(repair.store_orders, source.replace('mode = input->control;', 'mode = D_80400000[j].zero;').replace('D_80400000[5 + j].mode = D_80400000[j].zero;', 'D_80400000[5 + j].mode = D_80400000[5 + j].zero;'))
    assert not variants(repair.store_orders, source.replace('.zero = 0;\n', '.zero = 0; notify();\n'))


def test_counter_and_index_carriers_use_existing_declarations_and_raw_byte_anchor():
    candidate = variants(repair.counter_storage)[0][1]
    assert 'extern volatile u8 D_80300000;' in candidate
    assert 'volatile u32 totals[4];' in candidate
    assert not variants(repair.counter_storage, asm='')
    assert 'u32 slot = index & 0xFFFF;' in variants(repair.index_widths)[0][1]
    assert not variants(repair.index_widths, SOURCE.replace('u16 slot = index;', 'u16 slot = first - second;'))
    assert not variants(repair.index_widths, SOURCE.replace('block->totals[slot] =', 'slot++; block->totals[slot] ='))
    assert not variants(repair.index_widths, SOURCE.replace('u16 first, second, index, j;', 's32 first, second, index, j;'))


def test_conversion_movement_keeps_the_read_between_the_same_volatile_operations():
    source = SOURCE.replace('u32 ticks;', 'volatile u32 ticks;').replace(
        '            D_80400000[j].state =',
        '            fraction = (f32)D_80400000[j].ticks;\n            D_80400000[j].state =')
    candidate = variants(repair.conversion_orders, source)[0][1]
    assert 'state = input->rows[j].state;\n            fraction = (f32)D_80400000[j].ticks;' in candidate
    assert candidate.count('D_80400000[j].ticks') == source.count('D_80400000[j].ticks')
    assert not variants(repair.conversion_orders, source.replace('u8 state;', 'volatile u8 state;'))
    assert not variants(repair.conversion_orders, source.replace('ticks;\n            D_80400000[j].state', 'ticks; notify();\n            D_80400000[j].state'))


def test_byte_capture_and_case_order_keep_existing_indices_constants_and_narrowing():
    choices = variants(repair.byte_cases)
    captured = next(c for f, c in choices if f == 'indexed_record_byte_capture')
    assert "char __repair_byte = code[1]; first = __repair_byte - '0';" in captured
    ordered = next(c for f, c in choices if f == 'indexed_record_case_order')
    assert ordered.index("first = code[3]") < ordered.index("second = code[6]")
    assert not variants(repair.byte_cases, SOURCE.replace('char code[8];', 'volatile char code[8];'))
    assert not variants(repair.byte_cases, SOURCE.replace('code[2]', 'code[next()]').replace("case 'P':", "case 'P': notify();"))


def test_comments_and_macro_obscured_field_accesses_cannot_supply_a_repair_site():
    comment = "/* first = code[1] - '0';\nsecond = code[2] - '1'; */"
    source = SOURCE.replace('    switch (code[0]) {', comment+'\n    switch (code[0]) {')
    assert all(comment in candidate for _, candidate in variants(repair.byte_cases, source))
    assert not variants(repair.store_orders, header=HEADER+'\n#define zero state\n')
    assert not variants(repair.sequences, SOURCE+'\n/*'+('padding '*18000)+'*/')


@pytest.mark.parametrize('edit_source,edit_header', [
    (lambda s: s+'\n#define OBSERVED_LINE __LINE__\n', lambda h: h),
    (lambda s: s.replace('u32 ticks;', 'union { u32 ticks; float alternate; };'), lambda h: h),
    (lambda s: s, lambda h: h.replace('typedef unsigned int u32;', 'typedef unsigned short u32;')),
    (lambda s: s, lambda h: h.replace('typedef unsigned int u32;', 'typedef volatile unsigned int u32;')),
])
def test_unknown_or_observable_type_and_line_changes_decline(edit_source, edit_header):
    assert not variants(repair.sequences, edit_source(SOURCE), header=edit_header(HEADER))


def test_recipe_is_finite_deterministic_and_needs_neither_a_control_source_nor_a_compiler():
    first = variants(repair.sequences)
    assert first == variants(repair.sequences)
    assert 1 <= len(first) <= repair.SEQUENCE_LIMIT
    assert all(family == 'indexed_record_sequence' for family, _ in first)
    assert any('D_80400050[j]' in text and 'fraction = (f32)__repair_record_word;' in text for _, text in first)
    assert not variants(repair.sequences, asm='')
