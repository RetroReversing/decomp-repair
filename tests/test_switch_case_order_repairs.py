"""A switch's arms in other orders, and with the empty case its compare tree tests."""
from decomprepair import switch_case_order_repairs as o

SOURCE = '''void f(void) {
    switch (D) {
    case 0:
        if (E != 0) {
            D = 0x94;
            return;
        }
        break;
    case 16:
        D = 0xF;
        return;
    }
}
'''


def test_orders_and_the_empty_case_above():
    # An N64 function: exact with case 16 first and an empty `case 17:` (its tree tests `slti <17`); 82.4% without.
    texts = [t for family, t in o.variants(SOURCE, 'f') if family == 'switch_case_order']
    assert '''    case 0:
        if (E != 0) {
            D = 0x94;
            return;
        }
        break;
    case 16:
        D = 0xF;
        return;
    case 17:
        break;
    }
}''' in texts[0]
    swapped = '''    switch (D) {
    case 16:
        D = 0xF;
        return;
    case 0:'''
    assert any(swapped in t and 'case 17:' in t for t in texts)
    assert any(swapped in t and 'case 17:' not in t for t in texts)


def test_left_alone_when_an_arm_falls_through_or_holds_a_label():
    assert o.variants(SOURCE.replace('            return;\n        }\n        break;', '            return;\n        }'), 'f') == []
    assert o.variants(SOURCE.replace('        D = 0xF;\n', 'L1:\n        D = 0xF;\n'), 'f') == []
    assert o.variants('void f(void) {\n    switch (D) {\n    case 1:\n        break;\n    }\n}\n', 'f') == []


LOCAL_TAIL = '''
void f(int state, int ready) {
    switch (state) {
    case 2:
        finish();
        break;
    case 1:
        if (ready) {
            if (retry()) goto store_state;
            send();
        } else {
store_state:
            set_state();
        }
        break;
    }
}
'''


def test_can_reorder_an_arm_with_a_local_goto():
    choices = [text for family, text in o.variants(LOCAL_TAIL, 'f') if family == o.LOCAL_LABEL_FAMILY]
    assert any(text.index('case 1:') < text.index('case 2:') and 'case 3:' not in text
               and 'goto store_state;' in text for text in choices)


def test_leaves_cross_arm_jumps_and_conditional_exits_alone():
    external = LOCAL_TAIL.replace('        finish();', '        goto store_state;')
    fallthrough = LOCAL_TAIL.replace('        break;\n    }', '        if (ready) break;\n    }')
    assert not o.variants(external, 'f')
    assert not o.variants(fallthrough, 'f')
