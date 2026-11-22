"""A dead parameter as the loop's carrier with the body's reload split, and the three steps that lead to it.

One KMC GCC 2.7.2 function (an N64 voice-chain walk) went 1705 -> 1330 -> 905 -> 0 with `assignment_guard_sink`,
`default_arm_goto` and `param_loop_carrier`; the sources here keep its shape with neutral names."""
from decomprepair import assignment_guard_sink as sink
from decomprepair import default_arm_goto as default
from decomprepair import index_shift_spelling as spelling
from decomprepair import param_loop_carrier as carrier

WALK = '''s32 walk(u32 id) {
    s32 ret = -1;
    s32 head;
    s32 slot;
    s32 next;
    s32 byte;
    Node *node;
    Node *found;
    u32 key;
    head = -1;
    if (id != -1U) {
        found = NULL;
        node = first;
        if (node != NULL) {
            for (;;) {
                key = node->key;
                if (key == id) {
                    found = node;
                } else {
                    found = NULL;
                    if (id >= key) {
                        node = node->link;
                        if (node != NULL) {
                            continue;
                        }
                    }
                }
                break;
            }
        }
        if (found != NULL) head = found->head;
    }
    while (head != -1) {
        slot = (head & 0xFF) * 0x1A0;
        next = *(s32 *)(table + slot);
        if (*(s32 *)(check + slot) == head) {
            use(table + slot);
            head = *(u8 *)(table + slot + 0x63);
            last[head * 4] = 1;
            count = head;
            ret = 0;
        }
        head = next;
    }
    return ret;
}
'''


def test_guard_sink_moves_the_assignment_past_the_guard():
    (family, out), = sink.variants(WALK, 'walk')
    assert family == 'assignment_guard_sink'
    assert out.index('if (id >= key)') < out.index('found = NULL;', out.index('} else {'))
    assert out.count('found = NULL;') == 2


def test_guard_sink_left_alone():
    # the guard mentions the variable, has no `continue`, or is not the block's last statement
    assert sink.variants(WALK.replace('id >= key', 'found >= key'), 'walk') == []
    assert sink.variants(WALK.replace('continue;', 'key = 0;'), 'walk') == []
    assert sink.variants(WALK.replace('                    }\n                }\n                break;',
                                      '                    }\n                    key = 1;\n                }\n                break;'), 'walk') == []


def test_default_arm_goto_shares_the_skip_with_the_not_found_arm():
    (family, out), = default.variants(WALK.replace('        found = NULL;\n        node = first;', '        node = first;'), 'walk')
    assert family == 'default_arm_goto'
    assert 'if (id == -1U) {\n        goto __repair_default_head;' in out
    assert '} else {\n__repair_default_head:\n        head = -1;' in out
    assert 'if (found != NULL) {\n        head = found->head;' in out
    assert default.variants(WALK.replace('head = found->head;', 'head = found->head; head = 1;'), 'walk') == []


def test_default_arm_goto_needs_a_trailing_conditional_assignment():
    assert default.variants(WALK.replace('        if (found != NULL) head = found->head;\n', '        use(found);\n'), 'walk') == []


# the chain's last step starts from default_arm_goto's output: the head is first written after the lookup
GOTO = default.variants(WALK.replace('        found = NULL;\n        node = first;', '        node = first;'), 'walk')[0][1]


def test_param_loop_carrier_merges_and_splits_as_one_child():
    # the parameter's last use is the lookup; `head` is first written after it, outside any loop holding both
    out = dict.fromkeys(f for f, _ in carrier.variants(GOTO, 'walk'))
    assert set(out) == {'param_loop_carrier', 'redefined_web_split'}
    combined = [t for f, t in carrier.variants(GOTO, 'walk') if f == 'param_loop_carrier' and '__repair_web_id' in t]
    assert combined, 'the merge and the split come as one child'
    text = combined[0]
    assert 's32 head;' not in text and ' head ' not in text  # the local is gone: its name was the parameter's
    assert 'while (id != -1)' in text
    assert '__repair_web_id = *(u8 *)(table + slot + 0x63);' in text
    assert 'last[__repair_web_id * 4] = 1;' in text and 'count = __repair_web_id;' in text
    assert '        id = next;' in text  # the loop's own carrier keeps the parameter
    merged_only = [t for f, t in carrier.variants(GOTO, 'walk') if f == 'param_loop_carrier' and '__repair_web_id' not in t]
    assert merged_only and 'u32 __repair' not in merged_only[0]


def test_param_loop_carrier_refuses_unsafe_shapes():
    # the parameter is read after the local's first write
    late = GOTO.replace('        head = next;\n', '        head = next + id;\n')
    assert not [1 for f, t in carrier.variants(late, 'walk') if f == 'param_loop_carrier' and 's32 head;' not in t]
    # the parameter is used inside the loop that holds the local
    inside = GOTO.replace('slot = (head & 0xFF) * 0x1A0;', 'slot = (head & 0xFF) * 0x1A0 + id;')
    assert [f for f, _ in carrier.variants(inside, 'walk') if f == 'param_loop_carrier'] == []
    # the block's value is read after it before the loop reassigns it: no split
    live = GOTO.replace('            ret = 0;\n        }\n', '            ret = 0;\n        }\n        count = head;\n')
    assert not [1 for _, t in carrier.variants(live, 'walk') if '__repair_web_' in t]
    # an address taken: left to the compiler
    assert [f for f, _ in carrier.variants(GOTO.replace('use(table + slot);', 'use(&id);'), 'walk') if f == 'param_loop_carrier'] == []
    # a backward goto is a loop the structure scan does not see
    assert carrier.variants(GOTO.replace('    while (head != -1) {', 'again:\n    while (head != -1) {').replace(
        '    return ret;', '    if (ret) goto again;\n    return ret;'), 'walk') == []


def test_web_split_alone_for_a_local():
    source = WALK.replace('slot = (head & 0xFF) * 0x1A0;', 'slot = (head & 0xFF) * 0x1A0;\n        byte = 0;').replace(
        'head = *(u8 *)(table + slot + 0x63);', 'byte = *(u8 *)(table + slot + 0x63);').replace(
        'last[head * 4] = 1;', 'last[byte * 4] = 1;')
    assert all(f != 'redefined_web_split' or '__repair_web_' in t for f, t in carrier.variants(source, 'walk'))


def test_index_shift_spelling_both_ways():
    source = 'void f(void) { u8 i; i = g; *(tab + i * 4) = 1; tab2[i << 3] = 2; }\n'
    out = spelling.variants(source, 'f')
    texts = [t for _, t in out]
    assert any('*(tab + (i << 2)) = 1;' in t for t in texts)
    assert any('tab2[i * 8] = 2;' in t for t in texts)
    assert any('(i << 2)' in t and 'i * 8' in t for t in texts)  # all of them in one child
    assert spelling.variants('void f(void) { u8 i; i = g; x = i * 4; }\n', 'f') == []  # not an address
