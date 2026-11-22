"""A table search that m2c unrolled into goto copies, written once as an inline helper."""

from decomprepair import registry
from decomprepair.lookup_loop_inline import HELPER, PRIVATE, variants

# Two searches of one slot table (a busy byte and a key word at a stride), in m2c's shape: a counter, stride and key
# per copy, a `found_N` stub reached by a goto, a `join_N` label, and a goto that hops over the stubs.
SAVED = '''extern u8 busy_flags;
extern s32 slot_ids;
void put(s32);
void f(void *arg0, s32 *out) {
    s32 key_1;
    s32 key_2;
    s32 res_1;
    s32 res_2;
    s32 slot;
    s32 temp_id;
    s32 temp_id_2;
    s32 var_off_1;
    s32 var_off_2;
    u32 var_cnt_1;
    u32 var_cnt_2;

    var_cnt_1 = 0;
    temp_id = *(s32 *)((char *)(arg0) + 0);
    key_1 = temp_id & 0x7FFFFFFF;
    var_off_1 = 0;
loop_1:
    if (((*(u8 *)((char *)(&busy_flags) + var_off_1)) != 0) || ((*(s32 *)((char *)(&slot_ids) + var_off_1)) != key_1)) {
        var_cnt_1 += 1;
        var_off_1 += 0xFF8;
        if (var_cnt_1 >= 8U) {
            res_1 = -1;
        } else {
            goto loop_1;
        }
    } else {
        goto found_1;
    }
join_1:
    slot = res_1;
    if (slot != -1) {
        put(slot);
    }
    goto skip_2;
found_1: res_1 = var_cnt_1 | (temp_id & 0x80000000); goto join_1;
skip_2:
    var_cnt_2 = 0;
    temp_id_2 = *(s32 *)((char *)(arg0) + 8);
    key_2 = temp_id_2 & 0x7FFFFFFF;
    var_off_2 = 0;
loop_2:
    if (((*(u8 *)((char *)(&busy_flags) + var_off_2)) != 0) || ((*(s32 *)((char *)(&slot_ids) + var_off_2)) != key_2)) {
        var_cnt_2 += 1;
        var_off_2 += 0xFF8;
        if (var_cnt_2 >= 8U) {
            res_2 = -1;
        } else {
            goto loop_2;
        }
    } else {
        goto found_2;
    }
join_2:
    slot = res_2;
    if (slot != -1) {
        *out = slot;
    }
    return;
found_2: res_2 = var_cnt_2 | (temp_id_2 & 0x80000000); goto join_2;
}
'''


def _squash(text):
    return ' '.join(text.split())


def _by_family(source=SAVED):
    return {family: _squash(text) for family, text in variants(source, 'f')}


def test_the_searches_become_calls_of_one_helper():
    out = _by_family()[HELPER]
    assert 'void put(s32); static inline s32 find_entry(s32 id) {' in out
    assert 'for (; i < 8U; i++' not in out and 'for (; i < 8; i++, off += 0xFF8)' in out
    assert 'res_1 = find_entry(temp_id);' in out and 'res_2 = find_entry(temp_id_2);' in out
    assert 'return i | (id & 0x80000000);' in out
    assert 'find_entry(s32 id)' in out and out.count('static inline') == 1


def test_the_goto_copies_and_their_scaffolding_are_gone():
    out = _by_family()[HELPER]
    for gone in ('loop_', 'found_', 'join_', 'skip_2', 'goto', 'var_cnt_1', 'var_off_2', 'key_1', 'key_2'):
        assert gone not in out.split('void f(')[1], gone
    assert 'slot = res_1; if (slot != -1)' in out


def test_each_search_gets_an_id_and_slot_of_its_own():
    body = _by_family()[PRIVATE].split('void f(')[1]
    # the id is loaded into the local, the index written back into it, the guard reads it: one local per search
    assert 'slot_p = *(s32 *)((char *)(arg0) + 0); res_1 = find_entry(slot_p); slot_p = res_1; if (slot_p != -1) { put(slot_p); }' in body
    assert 'slot_p_ = *(s32 *)((char *)(arg0) + 8); res_2 = find_entry(slot_p_); slot_p_ = res_2; if (slot_p_ != -1) { *out = slot_p_; }' in body
    assert 's32 slot_p; s32 slot_p_;' in body or 's32 slot_p;' in body


def test_a_name_read_after_the_run_keeps_the_shared_local():
    src = SAVED.replace('        put(slot);\n    }\n    goto skip_2;', '        put(slot);\n    }\n    put(slot);\n    goto skip_2;')
    body = _by_family(src)[PRIVATE].split('void f(')[1]
    assert 'temp_id = *(s32 *)((char *)(arg0) + 0); res_1 = find_entry(temp_id); slot = res_1;' in body
    assert 'slot_p = *(s32 *)((char *)(arg0) + 8);' in body  # the second search still gets its own


def test_an_id_that_is_read_inside_the_block_keeps_the_shared_local():
    src = SAVED.replace('        put(slot);', '        put(temp_id);')
    body = _by_family(src)[PRIVATE].split('void f(')[1]
    assert 'find_entry(temp_id)' in body and 'put(temp_id)' in body


def test_the_for_form_with_continue_is_read_too():
    src = SAVED.replace('''loop_2:
    if (''', '''    for (;;) {
    if (''').replace('''            goto loop_2;
        }
    } else {
        goto found_2;
    }
join_2:''', '''            continue;
        }
    } else {
        goto found_2;
    }
    break;
    }
join_2:''')
    assert 'res_2 = find_entry(temp_id_2);' in _by_family(src)[HELPER]


def test_a_single_search_or_different_tables_are_left_alone():
    one = SAVED.replace('slot_ids) + var_off_2', 'other_ids) + var_off_2').replace('extern s32 slot_ids;', 'extern s32 slot_ids;\nextern s32 other_ids;')
    assert variants(one, 'f') == []


def test_a_stub_that_does_not_carry_the_flag_bit_is_left_alone():
    src = SAVED.replace('res_1 = var_cnt_1 | (temp_id & 0x80000000);', 'res_1 = var_cnt_1;')
    assert variants(src, 'f') == []


def test_a_name_already_used_gets_another_helper_name():
    src = SAVED.replace('void put(s32);', 'void put(s32);\nvoid find_entry(void);')
    assert 'static inline s32 find_entry_(s32 id)' in _by_family(src)[HELPER]


def test_the_family_declares_itself_for_every_caller():
    assert any(r.variants is variants for r in registry.declared())
