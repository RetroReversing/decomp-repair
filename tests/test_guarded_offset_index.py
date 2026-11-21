"""m2c's guarded counter loops with a byte offset beside the counter, indexed by the counter again."""
from decomprepair import guarded_offset_index as g

DRAFT = '''void f(void *arg0, f32 arg2) {
    s32 var_s1;
    s32 var_s1_2;
    s32 var_s2;
    s32 var_v1;

    var_s1 = 0;
    if ((*(s16 *)((char *)(arg0) + 0xC)) > 0) {
        var_s2 = 0;
        do {
            g(var_s2 + (*(s32 *)((char *)(arg0) + 0)));
            var_s1 += 1;
            var_s2 += 0x18;
        } while (var_s1 < (*(s16 *)((char *)(arg0) + 0xC)));
    }
    var_s1_2 = 0;
    if (((*(s16 *)((char *)(arg0) + 0xC)) - 1) > 0) {
        var_v1 = 0;
        do {
            h(var_v1 + (*(s32 *)((char *)(arg0) + 0)));
            var_s1_2 += 1;
            var_s1 = h(var_v1 + (*(s32 *)((char *)(arg0) + 4)));
            k(var_s1);
            var_v1 += 0x18;
        } while (var_s1_2 < ((*(s16 *)((char *)(arg0) + 0xC)) - 1));
    }
}
'''


def _only(source):
    return {family: text for family, text in g.variants(source, 'f')}


def test_offsets_become_counter_indices_and_the_bump_moves_last():
    out = _only(DRAFT)
    indexed = out[g.FAMILY]
    code = indexed.split('\n\n', 1)[1]
    assert 'var_s2' not in code and 'var_v1' not in code
    assert 'g((var_s1 * 0x18) + (*(s32 *)((char *)(arg0) + 0)));' in indexed
    # the early bump in the second loop moved after the last indexed use
    second = indexed[indexed.index('var_s1_2 = 0;'):]
    assert second.index('k(var_s1);') < second.index('var_s1_2 += 1;')
    assert 'if ((*(s16 *)((char *)(arg0) + 0xC)) > 0)' in indexed


def test_guards_and_the_shared_counter():
    out = _only(DRAFT)
    guarded = out[g.GUARD_FAMILY]
    assert 'if (var_s1 < (*(s16 *)((char *)(arg0) + 0xC))) {' in guarded
    assert 'if (var_s1_2 < ((*(s16 *)((char *)(arg0) + 0xC)) - 1)) {' in guarded
    shared = out[g.SHARED_FAMILY]
    assert shared.count('i = 0;') == 2 and 's32 i;' in shared
    assert 'if (i < ((*(s16 *)((char *)(arg0) + 0xC)) - 1)) {' in shared
    # the unrelated later value stays in its own variable
    assert 'var_s1 = h((i * 0x18) + (*(s32 *)((char *)(arg0) + 4)));' in shared
    assert 'k(var_s1);' in shared and 'var_s1_2' not in shared.split('\n\n', 1)[1]


def test_left_alone_when_the_offset_is_written_or_the_counter_read():
    written = DRAFT.replace('g(var_s2 +', 'var_s2 += 4; g(var_s2 +')
    assert g.FAMILY not in _only(written) or 'var_s2' in _only(written)[g.FAMILY]
    read = DRAFT.replace('g(var_s2 +', 'g(var_s1 + var_s2 +')
    first = _only(read).get(g.FAMILY, read)
    assert 'var_s2 += 0x18;' in first


def test_a_counter_read_after_its_loop_keeps_its_own_name():
    later = DRAFT.replace('    var_s1_2 = 0;\n', '    k(var_s1);\n    var_s1_2 = 0;\n', 1)
    assert g.SHARED_FAMILY not in _only(later)


def test_a_plain_counted_loop_takes_the_guard_and_shares_the_counter():
    # a counted loop with no offset beside its counter, mixed with m2c's offset loop
    mixed = DRAFT.replace('''        var_v1 = 0;
        do {
            h(var_v1 + (*(s32 *)((char *)(arg0) + 0)));
            var_s1_2 += 1;
            var_s1 = h(var_v1 + (*(s32 *)((char *)(arg0) + 4)));
            k(var_s1);
            var_v1 += 0x18;
        } while''', '''        do {
            h(var_s1_2);
            var_s1_2 += 1;
        } while''')
    out = _only(mixed)
    assert 'if (var_s1_2 < ((*(s16 *)((char *)(arg0) + 0xC)) - 1)) {' in out[g.GUARD_FAMILY]
    shared = out[g.SHARED_FAMILY]
    assert 'h(i);' in shared and 'g((i * 0x18) +' in shared


def test_an_escaping_counter_keeps_its_name_while_the_others_share():
    third = DRAFT.replace('''    }
}
''', '''    }
    var_s3 = 0;
    if ((*(s16 *)((char *)(arg0) + 0xE)) > 0) {
        do {
            h(var_s3);
            var_s3 += 1;
        } while (var_s3 < (*(s16 *)((char *)(arg0) + 0xE)));
    }
    k(var_s3);
}
''').replace('    s32 var_v1;\n', '    s32 var_v1;\n    s32 var_s3;\n')
    shared = _only(third)[g.SHARED_FAMILY]
    assert 'k(var_s3);' in shared and 'if (var_s3 < (*(s16 *)((char *)(arg0) + 0xE))) {' in shared
    assert 'g((i * 0x18) +' in shared and 'h((i * 0x18) +' in shared
