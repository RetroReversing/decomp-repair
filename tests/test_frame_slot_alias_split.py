import re

from decomprepair import frame_slot_alias_split
from decomprepair.frame_slot_alias_split import FAMILY, variants

SOURCE = """void make(void *arg0, s32 arg1) {
    struct {
        s32 sp30;
        s8 sp34;
        s32 sp38, sp3C, sp40;
        char reserved[20];
    } locals;
    void *rec;
    s32 result;

    locals.sp30 = 1;
    locals.sp34 = 1;
    scan(arg1, &locals.sp38, &locals.sp3C, &locals.sp40);
    rec = *(void **)((char *)arg0 + 0x3C);
    *((s32 *) (((char *) rec) + 0x34)) = alloc(*(u16 *)((char *)arg1 + 4) * 12, 2);
    if (((u32) (locals.sp40 - 1)) < 2U) {
        *((u16 *) (((char *) rec) + 0x42)) = (u16) locals.sp3C;
        result = locals.sp30 + locals.sp34;
    }
    *((s32 *) (((char *) rec) + 0x38)) |= result;
    locals.sp30 += 1;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_frame_reads_are_plain_dereferences_and_pointer_stores_are_record_members():
    children = variants(SOURCE, 'make')
    assert len(children) == 1 and children[0][0] == FAMILY
    text = _flat(children[0][1])
    # sp30 at 0, sp34 (a byte) at 4, sp38 at 8, sp3C at 12, sp40 at 16
    assert 'if (((u32) ((*(s32 *)((char *)&locals + 16)) - 1)) < 2U) {' in text
    assert '(u16) (*(s32 *)((char *)&locals + 12));' in text
    assert 'result = (*(s32 *)((char *)&locals + 0)) + locals.sp34;' in text
    assert '((__repair_rec_52_s32 *) rec)->f = alloc(' in text
    assert '((__repair_rec_66_u16 *) rec)->f = (u16)' in text
    assert '((__repair_rec_56_s32 *) rec)->f |= result;' in text
    assert text.index('typedef struct { char pad[52]; s32 f; } __repair_rec_52_s32;') < text.index('void make(')


def test_what_is_written_or_addressed_or_a_byte_stays():
    text = _flat(variants(SOURCE, 'make')[0][1])
    for kept in ('locals.sp30 = 1;', 'locals.sp34 = 1;', 'scan(arg1, &locals.sp38, &locals.sp3C, &locals.sp40);',
                 'locals.sp30 += 1;'):
        assert kept in text
    assert 'locals.sp34' in text and '(*(s8 *)' not in text


def test_nothing_without_a_frame_struct_a_pointer_store_or_a_read():
    assert variants('void f(void *p) { *((s32 *) (((char *) p) + 4)) = 1; }', 'f') == []
    plain = re.sub(r'\*\(\((?:s32|u16) \*\) \(\(\(char \*\) rec\) \+ 0x[0-9A-F]+\)\)[^;]*;', 'h();', SOURCE)
    assert variants(plain, 'make') == []
    assert variants(SOURCE.replace('char reserved[20];', 'struct pair reserved;'), 'make') == []


def test_the_family_is_registered():
    from decomprepair import registry
    assert any(entry.module.endswith('frame_slot_alias_split') for entry in registry.declared())
    assert frame_slot_alias_split.REPAIR['needs'] == ('source', 'name')
