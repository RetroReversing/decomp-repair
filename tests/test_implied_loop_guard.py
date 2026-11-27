from decomprepair import implied_loop_guard

HEAD = '''void shift(u16 i)
{
    u16 j;
'''
FOR = '''    for (j = 9; j > i; j--) {
        table[j] = table[j - 1];
    }
}
'''


def only(source):
    children = implied_loop_guard.variants(source, 'shift')
    assert [family for family, _ in children] == ['implied_loop_guard']
    return children[0][1]


def test_a_guard_around_a_for_that_tests_it_again():
    source = HEAD + '''    if (i < 9) {
        for (j = 9; j > i; j--) {
            table[j] = table[j - 1];
        }
    }
}
'''
    assert only(source) == HEAD + FOR


def test_a_guarded_do_while_with_the_start_before_or_inside_the_guard():
    before = HEAD + '''    j = 9;
    if ((u32) i < 9U) {
        do {
            table[j] = table[j - 1];
            j--;
        } while (j > i);
    }
}
'''
    inside = HEAD + '''    if (i < 9) {
        j = 9;
        do {
            table[j] = table[j - 1];
            j--;
        } while (j > i);
    }
}
'''
    assert only(before) == HEAD + FOR
    assert only(inside) == HEAD + FOR


def test_a_guard_that_is_not_the_first_test_stays():
    for guard in ('i < 8', 'i <= 9', 'i > 9', 'ready'):
        source = HEAD + f'''    if ({guard}) {{
        for (j = 9; j > i; j--) {{
            table[j] = 0;
        }}
    }}
}}
'''
        assert implied_loop_guard.variants(source, 'shift') == []


def test_an_else_a_second_statement_or_a_continue_stays():
    loop = 'for (j = 9; j > i; j--) { table[j] = 0; }'
    for body in (f'if (i < 9) {{ {loop} }} else {{ stop(); }}', f'if (i < 9) {{ {loop} stop(); }}',
                 'j = 9; if (i < 9) { do { if (table[j]) continue; j--; } while (j > i); }'):
        assert implied_loop_guard.variants(HEAD + '    ' + body + '\n}\n', 'shift') == []


def test_a_counter_read_after_a_guard_that_holds_its_start_stays():
    source = HEAD + '''    if (i < 9) {
        j = 9;
        do {
            j--;
        } while (j > i);
    }
    use(j);
}
'''
    assert implied_loop_guard.variants(source, 'shift') == []
