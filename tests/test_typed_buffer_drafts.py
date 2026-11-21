from test_ido_typed_drafts import with_labels

from decomprepair import draft_call_recovery, ido_buffer_drafts, kmc_buffer_drafts

QUEUE = '''
void put(void *items) {
    s32 next; s32 state; s32 limit;
    state = M2C_FIELD(items, s32 *, 0x54);
    if (state != 0) {
        if (state == 1) {
            limit = M2C_FIELD(items, s32 *, 0x58);
            if (limit >= M2C_FIELD(items, s32 *, 0x4C)) {
                M2C_FIELD(items, s32 *, 0x4C) = limit;
                M2C_FIELD(items, s32 *, 0x48) = 0;
                M2C_FIELD(items, s32 *, 0x40) = (s32) M2C_FIELD(items, s32 *, 0x44);
                goto join;
            }
        }
    } else {
join:
        *(items + (M2C_FIELD(items, s32 *, 0x40) * 4)) = M2C_FIELD(items, s32 *, 0x5C);
        next = M2C_FIELD(items, s32 *, 0x40) + 1;
        M2C_FIELD(items, s32 *, 0x40) = next;
        M2C_FIELD(items, s32 *, 0x40) = (s32) (next & 0xF);
    }
    M2C_FIELD(items, s32 *, 0x5C) = 0;
}
'''
HALFWORDS = '''
extern M2C_UNK spans;
extern M2C_UNK table;

void copy(s32 index, s32 out, s32 page, s32 slot) {
    s32 off; s32 i;
    *(&spans + ((index & 0xFFFF) * 0x64)) = out;
    i = 0;
    do {
        off = i * 2;
        *(off + out) = *(off + *(((slot & 0xFF) * 4) + *(((page & 0xFF) * 4) + &table)));
        i += 1;
    } while (i < 0x10);
}
'''
BANK = '''
M2C_UNK patch(void *, void *, M2C_UNK); /* extern */

void walk(void *ptr, M2C_UNK id) {
    s32 index;
    void *value;
    void *cursor;
    if (M2C_FIELD(ptr, s16 *, 0) == 0x22) {
        index = 0;
        if (M2C_FIELD(ptr, s16 *, 2) > 0) {
            cursor = ptr;
            do {
                value = M2C_FIELD(cursor, void **, 4) + ptr;
                M2C_FIELD(cursor, void **, 4) = value;
                if (value != NULL) {
                    patch(value, ptr, id);
                }
                index += 1;
                cursor += 4;
            } while (index < M2C_FIELD(ptr, s16 *, 2));
        }
    }
}
'''


def test_queue_keeps_both_writes_and_word_scaled_index():
    key = next(key for key, rule in ido_buffer_drafts._TARGETS.items() if rule[0] == 'ido_word_queue')
    asm = with_labels(key)
    [(family, result)] = draft_call_recovery.baseline_variants(QUEUE, 'put', asm, '', 'ido-7.1')
    assert family == 'ido_word_queue'
    assert 'items[items[0x40 / 4]] = items[0x5C / 4]' in result
    assert result.count('items[0x40 / 4] = items[0x40 / 4]') == 2
    assert not ido_buffer_drafts.variants(QUEUE, 'put', asm, 'void put(void *);')
    assert not ido_buffer_drafts.variants(QUEUE, 'put', asm.replace('andi $t5, $t3, 15', 'andi $t5, $t3, 31'))


def test_nested_table_keeps_byte_stride_and_halfword_element_type():
    asm = kmc_buffer_drafts._HALFWORDS.pattern.replace('\\', '')
    asm = with_labels(asm.replace('(?P<buffers>w+)', 'spans').replace('(?P=buffers)', 'spans')
                      .replace('(?P<pages>w+)', 'table').replace('(?P=pages)', 'table'))
    [(family, result)] = kmc_buffer_drafts.variants(HALFWORDS, 'copy', asm)
    assert family == 'kmc_nested_halfword_table'
    assert 'extern u8 spans[];' in result and 'extern void * table[];' in result
    assert 'spans[(index & 0xFFFF) * 100]' in result
    assert 'out[i] = ((u16 *)((void **)table[page & 255])[slot & 255])[i]' in result
    assert not kmc_buffer_drafts.variants(HALFWORDS, 'copy', asm, 'extern s32 spans;')


def test_relocation_walk_preserves_the_loaded_tag_and_forwarded_base():
    asm = kmc_buffer_drafts._BANK.pattern.replace('\\', '')
    asm = with_labels(asm.replace('(?P<tag>d+)', '34').replace('(?P<call>w+)', 'patch'))
    [(family, result)] = kmc_buffer_drafts.variants(BANK, 'walk', asm)
    assert family == 'kmc_typed_relocation_walk'
    assert 's16 tag; s16 count; u32 slots[1];' in result
    assert 'patch((void *)_m2c_buffer_obj->slots[_m2c_buffer_i], _m2c_buffer_base, _m2c_buffer_table)' in result
    assert not kmc_buffer_drafts.variants(BANK.replace('0x22', '0x23'), 'walk', asm)
