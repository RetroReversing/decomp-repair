from decomprepair import mips_regions, passthrough_argument_repairs
from decomprepair.switch_loop_repairs import CASE, COUNTER, EXACT, INDEX, LOOP, STORES, combine, variants

HEADER = '''
typedef signed char s8;
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;
'''
SWITCH = '''
void f(void) {
    char key[4];
    u16 row;
    u16 column;
    switch (key[0]) {
    case 3:
        row = (s8)key[1] - '0';
        column = (s8)key[2] - '1';
        break;
    }
}
'''
RECORD = '''
typedef struct {
    u8 value;
    volatile u8 cleared;
    u8 flags;
} Cell;
typedef struct {
    Cell cells[3][3];
    u32 values[3];
} Record;
typedef struct {
    u32 value;
    s32 flags;
} Input;
extern u8 count;
extern Cell left[3];
extern Cell right[3];
#define CONVERT(x) ((u32)((x) * 2))
'''
LOOP_BODY = '''
    for (i = 0; i < 3;) {
        previous = i++;
        value = CONVERT(input->value);
        ARRAY[previous].value = value;
        flag = *(volatile s32 *)&input->flags;
        ARRAY[previous].cleared = 0;
        ARRAY[previous].flags = flag;
    }
'''
LOOPS = RECORD+'''
void f(Input *input) {
    u16 i;
    u16 previous;
    u32 value;
    u8 flag;
'''+LOOP_BODY.replace('ARRAY','left')+LOOP_BODY.replace('ARRAY','right')+'}\n'
COUNTER_SOURCE = RECORD+'''
void f(Input *input, Record *bank) {
    u8 saved;
    u16 index;
    Record *record;
    index = 1;
    record = bank;
    saved = count;
    (*(volatile u32 *)&record->values[index]) = input->value;
    count = saved + 1;
}
'''
POINTER = RECORD+'''
u32 read_value(u32);
void f(Input *input, Record *bank) {
    u16 index;
    u16 i;
    u8 flag;
    u32 *value;
    Record *record;
    index = 1;
    record = bank;
    value = &record->values[index];
    *value = input->value;
    for (i = 0; i < 3; i++) {
        record->cells[index][i].value = read_value(*value);
        flag = *(volatile s32 *)&input->flags;
        record->cells[index][i].cleared = 0;
        record->cells[index][i].flags = flag;
    }
}
'''


def offered(src, family, **kwargs):
    return [text for label,text in variants(src,'f',HEADER,**kwargs) if label == family]


def test_explicit_signed_byte_loads_share_a_carrier_inside_one_case():
    [candidate] = offered(SWITCH, CASE)
    assert 's8 raw;' in candidate
    assert "raw = key[1];\n        row = raw - '0';\n        raw = key[2];" in candidate
    assert not offered(SWITCH.replace('        row =', '        if (column)\n        row ='), CASE)
    assert not offered(SWITCH.replace('key[2]', 'key[4]'), CASE)


def test_two_counted_loops_share_a_word_snapshot_and_keep_volatile_access():
    [candidate] = offered(LOOPS, LOOP)
    assert candidate.count('for (i = 0; (u16)i < 3; i++)') == 2
    assert candidate.count('u32 offset;') == 1
    assert candidate.count('offset = i;\n        flag = *(volatile s32 *)&input->flags;') == 2
    assert 'right[i].value = CONVERT(input->value);' in candidate
    assert 'left[offset].cleared = 0;' in candidate
    assert not offered(LOOPS.replace('        previous =', '        if (i) continue;\n        previous =',1), LOOP)
    assert not offered(LOOPS.replace('u16 previous;', 'u8 previous;'), LOOP)
    assert not offered(LOOPS.replace('((u32)((x) * 2))','((float)((x) * 2))'), LOOP)
    assert not offered(LOOPS.replace('((u32)((x) * 2))','((u32)((x)++))'), LOOP)


def test_snapshot_keeps_the_later_load_and_declines_pointer_escape_or_base_reassignment():
    [candidate] = offered(POINTER, INDEX)
    assert 'u32 stored;' in candidate
    assert 'stored = index;\n    record->values[index] = input->value;' in candidate
    assert 'read_value(record->values[stored])' in candidate
    assert not offered(POINTER.replace('    *value =', '    save_ptr(value);\n    *value ='), INDEX)
    assert not offered(POINTER.replace('    for (', '    record = input;\n    for ('), INDEX)
    assert not offered(POINTER.replace('    *value =', '    index++;\n    *value ='), INDEX)


def test_store_order_keeps_the_volatile_load_and_zero_store():
    [candidate] = offered(POINTER, STORES)
    assert (
        'record->cells[index][i].flags = *(volatile s32 *)&input->flags;\n'
        '        record->cells[index][i].cleared = 0;' in candidate)
    assert not offered(POINTER.replace('volatile u8 cleared;', 'u8 cleared;'), STORES)
    assert not offered(POINTER.replace('    }\n}', '    }\n    read_value(flag);\n}'), STORES)


def test_byte_and_halfword_staging_leave_the_final_unsigned_byte_wrap():
    word, byte = offered(COUNTER_SOURCE, COUNTER)
    assert 'u16 newIndex;' in word
    assert 'u8 newIndex;' in byte
    for text in (word,byte):
        assert 'newIndex = saved + 1;\n    count = newIndex;' in text
        assert 'extern u8 count;' in text
    assert not offered(COUNTER_SOURCE, EXACT)
    assert len(offered(COUNTER_SOURCE, EXACT, include_exact_only=True)) == 2
    assert not offered(COUNTER_SOURCE.replace('extern u8 count;', 'extern u16 count;'), COUNTER)
    assert not offered(COUNTER_SOURCE.replace('    count =', '    if (index)\n    count ='), COUNTER)


def test_pair_rechecks_both_guards_and_rejects_overlapping_edits():
    [snap] = offered(POINTER, INDEX)
    [order] = offered(POINTER, STORES)
    pair = combine(POINTER, snap, order, STORES, 'f', HEADER)
    assert pair and 'read_value(record->values[stored])' in pair and 'flags = *(volatile s32 *)' in pair
    assert combine(POINTER, snap, snap, INDEX, 'f', HEADER) is None


def test_passthrough_respects_delay_slot_clobbers_paths_and_confirmed_prototype():
    src = 'void g(int a, int b, int c);\nvoid f(int state) { g(1, 2, 3); }'
    untouched = 'addiu $a1, $zero, 1\naddiu $a2, $zero, 2\njal g\naddiu $a3, $zero, 3'
    offer = passthrough_argument_repairs.variants
    assert offer(src,'f',asm=untouched,arch='mips',require_evidence=True)
    assert not offer(src,'f',asm=untouched.replace('$a3','$a0'),arch='mips',require_evidence=True)
    assert not offer(src,'f',asm='beqz $v0, elsewhere\nnop\n'+untouched,arch='mips',require_evidence=True)
    assert not offer(src,'f',asm='jal other\nnop\n'+untouched,arch='mips',require_evidence=True)
    assert not offer(src,'f',asm=untouched,arch='mips',header='void g(int a, int b, int c);',require_evidence=True)
    assert not offer(src,'f',asm=untouched,arch='mips',callees='void g(int a, int b, int c) {}',require_evidence=True)
    saved = 'move $s0, $a0\njal other\nnop\nmove $a0, $s0\n'+untouched
    assert offer(src,'f',asm=saved,arch='mips',require_evidence=True)


def test_regions_understand_normalized_local_jump_and_branch_operands():
    targets = ['beqz $a0, .Lc', 'nop', 'nop', 'j f+0x14', 'nop', 'jr $ra', 'nop']
    graph = mips_regions.read(targets, symbol='f')
    assert graph['successors']['0'] == [2,3]
    assert graph['successors']['3'] == [5]
    assert mips_regions.read(targets, symbol='other') is None
    targets[0] = 'beqz $a0, 0xc [bytes 10800002]'
    assert mips_regions.read(targets, symbol='f') == graph
