"""compound_update_local: a global's or field's compound update written through a local updated in its own statement.

Synthetic shape of a 182-instruction SN64 GCC 2.8.1 allocator (945 -> 145 with no do-while fence): the header's byte
count `hdr.used += count * 12;` sits in the block that scales `count` by 8 for a call; through `t = hdr.used;
t += count * 12; hdr.used = t;` the add's pseudo has two sets and the first scheduler stops boosting it."""
from decomprepair import compound_update_local as s
from decomprepair import registry

SOURCE = '''typedef struct { u8 pad0[0x20]; s32 unk20; u8 pad24[4]; s32 used; } Pool;
extern Pool gPool;
extern s32 gCounts[];
extern s32 gEnd;
void fill(u8 *, s32, s32);

s32 reserve(s32 idx, u8 *buf) {
    s32 count;
    s32 end;

    end = gEnd;
    count = gCounts[idx];
    gPool.used += count * 12;
    count *= 8;
    fill(buf, end, count);
    end += count;
    return end;
}
'''


def _texts(source=SOURCE, name='reserve', header=''):
    return [text for family, text in s.variants(source, name, header, 'mips') if family == s.FAMILY]


def test_the_field_update_goes_through_a_local_of_the_field_type():
    texts = _texts()
    assert len(texts) == 2
    for text in texts:
        assert 'upd1 = gPool.used;\n    upd1 += count * 12;\n    gPool.used = upd1;' in text
        assert text.count('s32 upd1;') == 1
    # once after the last leading declaration, once first
    assert texts[0].index('s32 upd1;') > texts[0].index('s32 end;')
    assert texts[1].index('s32 upd1;') < texts[1].index('s32 count;')


def test_locals_are_left_alone():
    """`count *= 8` and `end += count` update locals: no memory, nothing to stage."""
    for text in _texts():
        assert 'count *= 8;' in text and 'end += count;' in text


def test_elements_globals_and_the_expanded_form():
    source = SOURCE.replace('gPool.used += count * 12;', 'gCounts[idx] = gCounts[idx] + count * 12;\n    gEnd -= 4;')
    texts = _texts(source)
    assert any('upd1 = gCounts[idx];\n    upd1 += count * 12;\n    gCounts[idx] = upd1;' in t for t in texts)
    assert any('upd2 = gEnd;\n    upd2 -= 4;\n    gEnd = upd2;' in t for t in texts)
    both = [t for t in texts if 'upd1 +=' in t and 'upd2 -=' in t]
    assert len(both) == 1


def test_a_lower_precedence_tail_is_not_a_compound_update():
    source = SOURCE.replace('gPool.used += count * 12;', 'gPool.used = gPool.used + count | 1;')
    assert _texts(source) == []


def test_side_effects_and_unknown_types_are_left_alone():
    assert _texts(SOURCE.replace('gPool.used += count * 12;', 'gPool.used += fill2(count);')) == []
    assert _texts(SOURCE.replace('gPool.used += count * 12;', 'gCounts[idx++] += 1;')) == []
    assert _texts(SOURCE.replace('gPool.used += count * 12;', 'gOther.used += 1;')) == []


def test_a_typed_dereference_takes_its_cast_type():
    source = SOURCE.replace('gPool.used += count * 12;', '*(u16 *)((char *)buf + 0x10) |= 2;')
    texts = _texts(source)
    assert texts and all('u16 upd1;' in t and 'upd1 |= 2;' in t for t in texts)


def test_registered():
    repair = registry.get('compound_update_local')
    assert repair is not None and s.FAMILY in repair.families
