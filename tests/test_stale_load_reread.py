import re

from decomprepair import stale_load_reread
from decomprepair.stale_load_reread import FAMILY, variants

SOURCE = """void place(void *rec, s32 *table) {
    s32 id;
    s32 flags;

    id = *((u16 *) (((char *) rec) + 0));
    flags = (*((u8 *) (((char *) ((id * 0x4C) + table)) + 0x46))) & 0x80;
    if (flags != 0) {
        *((s32 *) (((char *) rec) + 0x44)) = 0;
        use(*((s32 *) (((char *) ((id * 0x4C) + table)) + 0x34)), id);
    }
    done(id);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_each_use_after_a_store_or_a_call_is_one_child_and_all_of_them_another():
    children = [_flat(text) for family, text in variants(SOURCE, 'place') if family == FAMILY]
    load = '(*((u16 *) (((char *) rec) + 0)))'
    assert len(children) == 4
    assert any(load + ' * 0x4C) + table)) + 0x34)), id); } done(id);' in t for t in children)
    assert any('+ 0x34)), ' + load + '); } done(id);' in t for t in children)
    assert any('+ 0x34)), id); } done(' + load + ');' in t for t in children)
    every = [t for t in children if t.count(load) == 3]
    assert len(every) == 1 and 'done(id)' not in every[0]
    # the use that nothing separates from the load (the flags test) is never offered
    assert not any(load + ' * 0x4C) + table)) + 0x46' in t for t in children)


def test_children_change_only_a_use_into_the_load():
    load = '(*((u16 *) (((char *) rec) + 0)))'
    for _, text in variants(SOURCE, 'place'):
        assert text != SOURCE and load in text
        back = _flat(text).replace(load, 'id')
        assert back.count('id') >= _flat(SOURCE).count('id') - 0 and 'id = *((u16 *) (((char *) rec) + 0));' in back


def test_nothing_when_the_name_is_assigned_twice_the_pointer_moves_or_nothing_separates_the_use():
    twice = SOURCE.replace('    flags = (*', '    id = 3;\n    flags = (*')
    assert variants(twice, 'place') == []
    moved = SOURCE.replace('        *((s32 *) (((char *) rec) + 0x44)) = 0;', '        rec = table;')
    assert not [t for _, t in variants(moved, 'place') if 'use(*((s32 *) (((char *) (((*((u16' in _flat(t)]
    tight = 'void f(void *p) { s32 a; s32 b; a = *((u16 *) (((char *) p) + 4)); b = a * 2; g(b); }'
    assert variants(tight, 'f') == []
    wide = SOURCE.replace('id = *((u16 *)', 'id = *((f64 *)')
    assert variants(wide, 'place') == []


def test_the_family_is_registered():
    from decomprepair import registry
    assert any(entry.module.endswith('stale_load_reread') for entry in registry.declared())
    assert stale_load_reread.REPAIR['needs'] == ('source', 'name')
