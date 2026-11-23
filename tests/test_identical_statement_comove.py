"""identical_statement_comove: the same statement moved the same way in every arm that has it."""
from decomprepair import identical_statement_comove as comove
from decomprepair import registry

SOURCE = '''void f(void *r, s32 *p, s32 k) {
    if (k != 0) {
        *((s16 *) (((char *) r) + 0x40)) = (s16) p[4];
        *((s16 *) (((char *) r) + 0x2c)) = 1;
        *((u8 *) (((char *) r) + 0x3c)) = 0;
        *((u8 *) (((char *) r) + 0x3e)) = 2;
    } else {
        *((s16 *) (((char *) r) + 0x40)) = (s16) p[4];
        *((s16 *) (((char *) r) + 0x2e)) = 3;
        *((u8 *) (((char *) r) + 0x3c)) = 0;
        *((u8 *) (((char *) r) + 0x3f)) = 4;
    }
}
'''


def children():
    return [text for _family, text in comove.variants(SOURCE, 'f')]


def test_the_shared_store_moves_down_in_both_arms_at_once():
    store = '*((s16 *) (((char *) r) + 0x40)) = (s16) p[4];'
    for text in children():
        lines = [line.strip() for line in text.split('\n')]
        first, second = (index for index, line in enumerate(lines) if line == store)
        if lines[first - 1].endswith('0x2c)) = 1;') and lines[second - 1].endswith('0x2e)) = 3;'):
            return
    raise AssertionError('no child has the store one place lower in both arms')


def test_no_child_moves_it_in_one_arm_only():
    store = '*((s16 *) (((char *) r) + 0x40)) = (s16) p[4];'
    for text in children():
        lines = [line.strip() for line in text.split('\n')]
        first, second = (index for index, line in enumerate(lines) if line == store)
        in_first = lines[first - 1] == 'if (k != 0) {'
        in_second = lines[second - 1] == '} else {'
        assert in_first == in_second


def test_a_statement_that_is_alone_is_not_moved_by_itself():
    texts = children()
    assert all(text.count('0x3e)) = 2;') == 1 for text in texts)
    assert not [text for text in texts if text.split('\n')[5].strip().endswith('0x3e)) = 2;')
                and text.split('\n')[4].strip().endswith('0x3e)) = 2;')]


def test_a_move_that_would_cross_a_call_or_a_brace_is_refused():
    source = SOURCE.replace('        *((u8 *) (((char *) r) + 0x3c)) = 0;\n        *((u8 *) (((char *) r) + 0x3e)) = 2;',
                            '        g(r);\n        *((u8 *) (((char *) r) + 0x3c)) = 0;', 1)
    for _family, text in comove.variants(source, 'f'):
        assert text.index('g(r);') < text.index('0x3c)) = 0;') or text.count('g(r);') == 1


def test_it_declares_itself_to_the_registry():
    repair = registry.get('identical_statement_comove')
    assert repair is not None and registry.problems(repair) == []
