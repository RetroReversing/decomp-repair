import re

from decomprepair.complement_late import BOTH_FAMILY, FAMILY, PLAIN_FAMILY, variants

SOURCE = """typedef struct {
    volatile u32 used;
    u8 alignment;
} Tag;

extern Tag gTags[];
extern u32 gBottom;

u32 pick(s32 size, s32 tag) {
    s32 mask = gTags[tag].alignment - 1;
    if (tag == 45) {
        return 0;
    } else {
        u32 old;
        u32 used;
        u32 start;
        u32 temp;
        u32 inverse;
        do { inverse = ~mask; } while (0);
        old = gBottom;
        used = gTags[tag].used;
        temp = old + mask;
        start = temp & inverse;
        gBottom = start + size;
        gTags[tag].used = used + (start + size - old);
        return start;
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(family, source=SOURCE):
    return [_flat(text) for kind, text in variants(source, 'pick') if kind == family]


def test_the_complement_moves_after_the_sum_in_both_operand_orders():
    found = _found(FAMILY)
    assert any('temp = old + mask; inverse = ~mask; start = temp & inverse;' in t for t in found), found
    assert any('temp = old + mask; inverse = ~mask; start = inverse & temp;' in t for t in found), found
    assert all('do { inverse' not in t for t in found)


def test_the_combination_also_reads_the_volatile_member_plainly():
    found = _found(BOTH_FAMILY)
    assert any('used = *(u32 *)&gTags[tag].used; temp = old + mask; inverse = ~mask; start = inverse & temp;' in t
               for t in found), found
    # a store to the member stays as it is
    assert all('gTags[tag].used = used +' in t for t in found)


def test_volatile_member_reads_alone():
    found = _found(PLAIN_FAMILY)
    assert any('used = *(u32 *)&gTags[tag].used;' in t and 'do { inverse = ~mask; } while (0);' in t for t in found)


def test_nothing_when_the_complement_is_read_twice_or_the_mask_changes_first():
    twice = SOURCE.replace('return start;', 'return start | inverse;')
    assert _found(FAMILY, twice) == []
    changed = SOURCE.replace('old = gBottom;', 'old = gBottom;\n        mask += 1;')
    assert _found(FAMILY, changed) == []


def test_nothing_when_no_operand_is_computed_after_it():
    early = SOURCE.replace('        temp = old + mask;\n', '').replace('        do { inverse = ~mask; } while (0);\n',
                                                                       '        temp = old + mask;\n        do { inverse = ~mask; } while (0);\n')
    assert _found(FAMILY, early) == []
