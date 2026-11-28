import re

from decomprepair.constant_into_reading_arm import FAMILY, variants

ARMS = """void tick(Obj *obj) {
    s32 flag;
    flag = 1;
    if (obj->kind == 0) {
        if (gPage != 1) {
            reset();
        }
    } else {
        gCount += flag;
        flag ^= gCount < 2;
        if (flag != 0) {
            spawn();
        }
    }
    done(obj);
}
"""

GUARD = """void tick(Obj *obj) {
    s32 flag;
    flag = 1;
    if (obj->kind == 0) {
        reset();
        goto out;
    }
    gCount += 1;
    if (gTwo != 0) {
        flag = (gCount < 2) ^ 1;
    }
    if (flag != 0) {
        spawn();
    } else {
out:
        done(obj);
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(source):
    return [_flat(text) for family, text in variants(source, 'tick') if family == FAMILY]


def test_the_constant_heads_the_only_arm_that_reads_it():
    found = _found(ARMS)
    assert len(found) == 1
    assert 'else { flag = 1; gCount += flag;' in found[0]
    assert 's32 flag; if (obj->kind == 0)' in found[0]


def test_the_constant_moves_past_a_guard_that_leaves():
    found = _found(GUARD)
    assert len(found) == 1
    assert 'goto out; } flag = 1; gCount += 1;' in found[0]


def test_a_value_read_on_both_sides_or_after_stays():
    assert not _found(ARMS.replace('reset();', 'gPage = flag;'))
    assert not _found(ARMS.replace('done(obj);', 'done(flag);'))
    assert not _found(ARMS.replace('obj->kind == 0', 'obj->kind == flag'))
    assert not _found(GUARD.replace('done(obj);', 'done(flag);'))
    assert not _found(GUARD.replace('        goto out;\n', ''))


def test_a_global_or_an_address_taken_local_stays():
    assert not _found(ARMS.replace('    s32 flag;\n', ''))
    assert not _found(ARMS.replace('done(obj);', 'done(obj);\n    keep(&flag);'))
