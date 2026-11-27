"""m2c's draft of "copy two tables to the frame, search one, call by the id found" turned back into the game's shape."""
from decomprepair import (
    block_move_struct_assign,
    guarded_search_else,
    shared_value_inline,
    slot_scalar_records,
    target_call_arity_repairs,
)

DRAFT = """extern s32 gIds;
extern char gCounts[];
extern char gNames[];

void pick(s32 arg0) {
    u8 sp[256];
    s32 sp10;
    s32 sp108;
    s32 *var_a1;
    s32 *var_v1_2;
    char *var_v0;
    char *var_v1;
    s32 var_a2;
    s32 var_v0_2;

    var_v1 = &sp10;
    var_v0 = &gIds;
    do {
        M2C_FIELD(var_v1, s32 *, 0) = M2C_FIELD(var_v0, s32 *, 0);
        M2C_FIELD(var_v1, s32 *, 4) = (s32) M2C_FIELD(var_v0, s32 *, 4);
        M2C_FIELD(var_v1, s32 *, 8) = (s32) M2C_FIELD(var_v0, s32 *, 8);
        M2C_FIELD(var_v1, s32 *, 0xC) = (s32) M2C_FIELD(var_v0, s32 *, 0xC);
        var_v0 += 0x10;
        var_v1 += 0x10;
    } while (var_v0 != (gIds + 0xF0));
    *(s32 *)var_v1 = *(s32 *)var_v0;
    var_v1_2 = gCounts;
    var_a1 = &sp108;
    if ((s32) &gCounts & 3) {
        do {
            M2C_FIELD(var_a1, s32 *, 0) = M2C_UNALIGNED32(M2C_FIELD(var_v1_2, s32 *, 0));
            M2C_FIELD(var_a1, s32 *, 4) = M2C_UNALIGNED32(M2C_FIELD(var_v1_2, s32 *, 4));
            M2C_FIELD(var_a1, s32 *, 8) = M2C_UNALIGNED32(M2C_FIELD(var_v1_2, s32 *, 8));
            M2C_FIELD(var_a1, s32 *, 0xC) = M2C_UNALIGNED32(M2C_FIELD(var_v1_2, s32 *, 0xC));
            var_v1_2 += 0x10;
            var_a1 += 0x10;
        } while (var_v1_2 != (gCounts + 0x30));
    } else {
        do {
            M2C_FIELD(var_a1, s32 *, 0) = (s32) M2C_FIELD(var_v1_2, s32 *, 0);
            M2C_FIELD(var_a1, s32 *, 4) = (s32) M2C_FIELD(var_v1_2, s32 *, 4);
            M2C_FIELD(var_a1, s32 *, 8) = (s32) M2C_FIELD(var_v1_2, s32 *, 8);
            M2C_FIELD(var_a1, s32 *, 0xC) = (s32) M2C_FIELD(var_v1_2, s32 *, 0xC);
            var_v1_2 += 0x10;
            var_a1 += 0x10;
        } while (var_v1_2 != (gCounts + 0x30));
    }
    M2C_FIELD(var_a1, s8 *, 0) = (s8) M2C_FIELD(var_v1_2, s8 *, 0);
    M2C_FIELD(var_a1, s8 *, 1) = (s8) M2C_FIELD(var_v1_2, s8 *, 1);
    M2C_FIELD(var_a1, s8 *, 2) = (s8) M2C_FIELD(var_v1_2, s8 *, 2);
    var_a2 = 0;
    if (arg0 != 0x2710) {
        if (sp10 != arg0) {
            var_v0_2 = 0 & 0xFFFF;
loop_11:
            if ((&sp10)[var_v0_2] != 0x2710) {
                var_a2 += 1;
                var_v0_2 = var_a2 & 0xFFFF;
                if ((&sp10)[var_a2 & 0xFFFF] == arg0) {
                    goto block_13;
                }
                goto loop_11;
            }
        } else {
block_13:
            load((&sp10)[var_a2 & 0xFFFF], M2C_FIELD((sp + var_a2), u8 *, 0x108), var_a2, &sp10);
        }
    }
}
"""

ASM = """    sll   $v0, $a2, 2
    lw    $a0, 0x10($v0)
    lbu   $a1, 0x108($v0)
    jal   load
    nop
"""


def test_block_moves_read_zero_offset_member_and_bounded_unaligned_loop():
    text = DRAFT
    for _ in range(2):
        text = block_move_struct_assign.variants(text, 'pick')[0][1]
    assert '__repair_blockF4w' in text and '__repair_block33 ' in text
    assert 'while' not in text.split('var_a2 = 0;')[0]


def test_slot_scalars_become_the_records():
    [(family, text)] = slot_scalar_records.variants(DRAFT, 'pick')
    assert family == 'slot_scalar_records'
    assert '    __repair_blockF4w sp10;\n    __repair_block33 sp108;\n' in text
    assert 'u8 sp[256]' not in text
    assert 'sp10.data[0] != arg0' in text and 'sp108.data[var_a2]' in text and 'sp10.data);' in text


def test_search_in_else_arm_becomes_while_and_drops_stray_arguments():
    text = slot_scalar_records.variants(DRAFT, 'pick')[0][1]
    plain, trimmed = [t for _, t in guarded_search_else.variants(text, 'pick', ASM)]
    assert 'while (sp10.data[var_a2] != arg0) {' in plain and 'u16 var_a2;' in plain
    assert 'goto' not in plain and 'var_v0_2' not in plain
    assert 'sp108.data[var_a2]);' in trimmed and 'var_a2, sp10.data' not in trimmed


def test_search_declines_when_code_follows_the_else_arm():
    text = slot_scalar_records.variants(DRAFT, 'pick')[0][1]
    text = text.rstrip()[:-1] + '    done();\n}\n'
    assert not guarded_search_else.variants(text, 'pick')


def test_tail_merged_calls_take_the_targets_arity():
    source = """void f(s32 a) {
    u16 i;
    if (a) {
        load(names[0], 1, i, ids);
    } else {
        load(names[1], 2, i, ids);
    }
}
"""
    children = target_call_arity_repairs.variants(source, 'f', ASM)
    assert any('load(names[0], 1);' in t and 'load(names[1], 2);' in t for _, t in children)


SHARED = """void f(s32 arg0) {
    Ids ids;
    s32 temp_v0;
    s32 temp_a0;
    s32 temp_v1;
    u16 i;

    ids = gIds;
    i = arg0;
    temp_v0 = i;
    temp_a0 = temp_v0 * 4;
    temp_v1 = ids.data[temp_v0];
    if (temp_v1 == 1) {
        load(*(s32 *)(temp_a0 + gNames), 3);
    } else if (temp_v1 == 2) {
        load(*(s32 *)(temp_a0 + gNames), 4);
    }
}
"""


def test_shared_values_are_written_out_together():
    [(_, text)] = shared_value_inline.variants(SHARED, 'f')
    assert 'temp_' not in text
    assert 'if (ids.data[i] == 1)' in text and '*(s32 *)((i * 4) + gNames)' in text


def test_shared_values_stay_when_the_array_escapes():
    escaped = SHARED.replace('load(*(s32 *)(temp_a0 + gNames), 3);', 'load(ids.data, 3);')
    assert all('temp_v1' in t for _, t in shared_value_inline.variants(escaped, 'f'))
