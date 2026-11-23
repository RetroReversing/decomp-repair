import re

from decomprepair import frame_write_alias_split
from decomprepair.frame_write_alias_split import FAMILY, variants

SOURCE = """void make(void **arg0, s32 arg1) {
    struct {
        s32 sp30;
        s8 sp34;
        s32 sp38;
        char reserved[20];
    } locals;
    void *rec;
    s32 count;

    rec = *((void **) (((char *) (*arg0)) + 0x3C));
    locals.sp30 = 1;
    clear(&locals.sp30);
    count = *((u16 *) (((char *) arg1) + 4));
    locals.sp34 = 2;
    locals.sp38 |= count;
    *((s32 *) (((char *) rec) + 0x34)) = count;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_a_slot_write_and_the_pointer_accesses_beside_it_are_one_child():
    texts = [_flat(text) for family, text in variants(SOURCE, 'make') if family == FAMILY]
    both = [t for t in texts if 'locals.sp30 = 1' not in t and '(*(s32 *)((char *)&locals + 0)) = 1;' in t]
    assert both
    before = [t for t in both if 'rec = ((__repair_rec_60_void_p *) (*arg0))->f;' in t]
    assert before
    assert all('typedef struct { char pad[60]; void * f; } __repair_rec_60_void_p;' in t.split('void make(')[0]
               for t in before)
    # the neighbour after the write holds no dereference (a call): only the one before is rewritten there
    assert not any('clear((' in t and '->f' in t.split('clear(')[1] for t in before)


def test_the_neighbour_after_a_write_is_rewritten_too_and_a_byte_slot_is_left_alone():
    texts = [_flat(text) for _, text in variants(SOURCE, 'make')]
    after = [t for t in texts if '(*(s32 *)((char *)&locals + 8)) |= count;' in t]
    assert after and all('->f = count;' in t for t in after)
    assert not any('(*(s8 *)' in t or '&locals + 4)' in t for t in texts)
    assert all('locals.sp34 = 2;' in t for t in texts)
    assert all('clear(&locals.sp30);' in t for t in texts)


def test_children_differ_from_the_source_only_by_those_rewrites_and_never_repeat():
    children = variants(SOURCE, 'make')
    assert children and len({text for _, text in children}) == len(children)
    for _, text in children:
        assert text != SOURCE and 'typedef struct' in text


def test_nothing_without_a_frame_struct_or_a_neighbouring_dereference():
    assert variants('void f(void *p) { *((s32 *) (((char *) p) + 4)) = 1; }', 'f') == []
    bare = SOURCE.replace('rec = *((void **) (((char *) (*arg0)) + 0x3C));', 'rec = 0;')
    bare = bare.replace('count = *((u16 *) (((char *) arg1) + 4));', 'count = 0;')
    bare = bare.replace('*((s32 *) (((char *) rec) + 0x34)) = count;', 'use(count);')
    assert variants(bare, 'make') == []


def test_a_record_already_declared_is_not_declared_again_and_the_family_is_registered():
    once = variants(SOURCE, 'make')[0][1]
    again = [text for _, text in variants(once, 'make')]
    for text in again:
        for record in set(re.findall(r'typedef struct \{[^}]*\} (__repair_rec_\w+);', text)):
            assert len(re.findall(rf'\}} {record};', text)) == 1
    from decomprepair import registry
    assert any(entry.module.endswith('frame_write_alias_split') for entry in registry.declared())
    assert frame_write_alias_split.REPAIR['needs'] == ('source', 'name')
