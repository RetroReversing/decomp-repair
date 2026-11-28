from decomprepair import registry
from decomprepair.stack_slot_record_copy import BUMP_LATE, FAMILY, UNFENCED, variants

SOURCE = '''extern s32 gTable;
extern s32 gCount;

#define sp0 (*(s32 *)(sp + 0x0))
#define sp4 (*(s32 *)(sp + 0x4))
#define sp8 (*(s32 *)(sp + 0x8))
#define spC (*(s32 *)(sp + 0xC))
void append(void *arg0) {
    s32 *count;
    u8 sp[16];
    s32 n;
    void *slot;

    do { count = &gCount; n = (*count); } while (0);
    if (n < 64) {
        sp0 = (s32) M2C_FIELD(arg0, f32 *, 0);
        do { sp4 = (s32) M2C_FIELD(arg0, f32 *, 8); } while (0);
        do { do { (*count) = n + 1; } while (0); } while (0);
        do { sp8 = (s32) M2C_FIELD(arg0, f32 *, 4); } while (0);
        slot = (n * 0x10) + gTable;
        M2C_FIELD(slot, s32 *, 8) = sp8;
        M2C_FIELD(slot, s32 *, 4) = sp4;
        M2C_FIELD(slot, s32 *, 0) = sp0;
        M2C_FIELD(slot, s32 *, 0xC) = spC;
    }
}
'''


def _children(source=SOURCE):
    return dict(variants(source, 'append'))


def test_the_stores_become_one_record_copy():
    text = _children()[FAMILY]
    assert 'typedef struct { s32 w[4]; } __repair_slots4;' in text
    assert '__repair_slots4 __repair_frame;' in text
    assert '*(__repair_slots4 *) ((s8 *) (slot)) = __repair_frame;' in text
    assert '__repair_frame.w[2] = (s32) M2C_FIELD(arg0, f32 *, 4);' in text
    assert 'u8 sp[16]' not in text and '#define sp' not in text and 'M2C_FIELD(slot' not in text


def test_the_counter_bump_goes_below_the_last_member_with_the_fences_opened():
    children = _children()
    assert 'do {' not in children[UNFENCED]
    late = children[BUMP_LATE]
    assert 'do {' not in late
    assert late.count('(*count) = n + 1;') == 1
    assert late.index('__repair_frame.w[2] =') < late.index('(*count) = n + 1;') < late.index('*(__repair_slots4 *)')


def test_a_bump_inside_a_condition_stays():
    source = SOURCE.replace('do { do { (*count) = n + 1; } while (0); } while (0);', 'if (n) { (*count) = n + 1; }')
    assert BUMP_LATE not in _children(source)


def test_declines_when_the_frame_is_used_in_another_way():
    assert not variants(SOURCE.replace('slot = (n', 'use(sp); slot = (n'), 'append')
    assert not variants(SOURCE.replace('slot = (n', 'use(&sp4); slot = (n'), 'append')
    assert not variants(SOURCE.replace('        M2C_FIELD(slot, s32 *, 0xC) = spC;\n', ''), 'append')
    assert not variants(SOURCE.replace('(*(s32 *)(sp + 0x4))', '(*(f32 *)(sp + 0x4))'), 'append')


def test_declares_itself():
    assert any(entry.module == 'stack_slot_record_copy' for entry in registry.declared())
