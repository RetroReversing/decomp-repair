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
