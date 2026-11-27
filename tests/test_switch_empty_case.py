"""An empty case added in the gaps of a switch's labels."""
from decomprepair import switch_empty_case

SOURCE = '''void f(int s) {
    switch (s) {
    case 0:
        g(0);
        break;
    case 2:
        g(2);
        break;
    case 3:
        g(3);
        break;
    case 0x384:
        g(4);
        break;
    }
}
'''


def test_a_case_in_each_gap_and_above():
    children = [child for _, child in switch_empty_case.variants(SOURCE, 'f')]
    assert any('case 1: break;' in child for child in children)
    assert any('case 4: break;' in child for child in children)
    assert any('case 0x385: break;' in child for child in children)
    assert all(child.count('{') == child.count('}') for child in children)


def test_with_a_default_the_label_joins_it_and_a_falling_arm_keeps_its_exit():
    with_default = SOURCE.replace('''    }
}''', '''    default:
        g(9);
    }
}''')
    assert any('case 1: default:' in child for _, child in switch_empty_case.variants(with_default, 'f'))
    falling = SOURCE.replace('''        g(4);
        break;''', '        g(4);')
    assert all('break; case ' in child for _, child in switch_empty_case.variants(falling, 'f'))


def test_a_dense_or_small_switch_is_left_alone():
    assert switch_empty_case.variants('void f(int s) { switch (s) { case 0: break; case 1: break; } }', 'f') == []
