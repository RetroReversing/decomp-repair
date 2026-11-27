from decomprepair import filter_switch_cases

DRAFT = '''extern s32 busy;
void f(s16 id) {
    s16 index;

    if (id < 0xA3) {
        index = id - 1;
        if (busy != 0) {
            switch (index);                       /* jump table: jtbl_80001520 */
        } else {
            play(id);
block_8:
            stop(id);
        }
    }
}
'''
PASS, LEAVE = 0x1000, 0x2000
TABLES = [(0, [PASS, LEAVE, LEAVE, PASS, LEAVE, LEAVE])]


def test_the_values_that_reach_the_shared_code_become_a_filter_before_it():
    children = filter_switch_cases.variants(DRAFT, 'f', TABLES)
    family, text = children[0]
    assert family == 'filter_switch_cases'
    assert ('switch (index) {\n' in text and 'case 0:\n' in text and 'case 3:\n' in text
            and 'default:' in text and 'return;' in text)
    assert 'else' not in text and text.count('play(id);') == 1 and 'case 1:' not in text
    # the other destination as the passing set is offered too
    assert any('case 1:' in other and 'case 0:' not in other for _, other in children)


def test_a_lowest_value_read_from_a_subtraction_is_also_offered_from_zero():
    texts = [text for _, text in filter_switch_cases.variants(DRAFT, 'f', [(1, TABLES[0][1])])]
    assert any('case 1:' in text and 'case 4:' in text for text in texts)
    assert any('case 0:' in text and 'case 3:' in text for text in texts)


def test_nothing_without_a_two_way_table_or_when_leaving_early_would_skip_code():
    assert filter_switch_cases.variants(DRAFT, 'f') == []
    assert filter_switch_cases.variants(DRAFT, 'f', [(0, [PASS, LEAVE, 0x3000])]) == []
    followed = DRAFT.replace('        }\n    }\n}\n', '        }\n        done();\n    }\n}\n')
    assert filter_switch_cases.variants(followed, 'f', TABLES) == []
    # `return` inside a loop would skip its later rounds, and after `else` the shared code would run for both paths
    looped = DRAFT.replace('    if (id < 0xA3) {', '    while (id < 0xA3) {')
    assert filter_switch_cases.variants(looped, 'f', TABLES) == []
    chained = DRAFT.replace('        if (busy != 0) {', '        if (id == 0) { play(0); } else if (busy != 0) {')
    assert filter_switch_cases.variants(chained, 'f', TABLES) == []
    assert filter_switch_cases.variants(DRAFT.replace('void f', 's32 f'), 'f', TABLES) == []
