"""A selected nullary definition can remove an extra argument in a paired repair."""

from decomprepair.no_input_call_join import FAMILY, variants, witnesses

SOURCE = """\
void *list_head(s8);
void visit(void)
{
    void *current;
    void *node;
    s32 mode;
    s32 port;
    current = initial();
    port = get_port();
    mode = 0;
    if (current == NULL) {
        mode = 1;
        node = list_head(port);
        goto check_mode;
    }
    node = next(current);
    if (choose(port)) {
        mode = 1;
    }
    check_mode:
    if (mode != 0) {
        current = NULL;
        inspect(node);
    }
    current = NULL;
    report(current);
}
"""
GETTER = 'extern s32 root; s32 list_head(void) { return root; }'
CALLEES = {'list_head': GETTER}
ROWS = [
    ('i', 'bnez $v0, .Lnext', 'bnez $v0, .Lelse'),
    (' ', 'move $a0, $s4', 'move $a0, $s4'),
    ('o', '', 'addiu $s3, $zero, 1'),
    (' ', 'jal list_head', 'jal list_head'),
    ('o', 'addiu $s3, $zero, 1', 'move $a0, $s4'),
    (' ', 'nop', 'nop'),
    ('<', 'move $v0, $s3', ''),
    ('r', 'beqz $v0, .Lskip', 'beqz $s3, .Lskip'),
    (' ', 'nop', 'nop'),
]


def test_uses_the_selected_signature_and_the_dead_join_pointer():
    assert witnesses(ROWS) == {'list_head'}
    [(label, changed)] = variants(SOURCE, 'visit', ROWS, '#define NULL ((void *) 0)', CALLEES)
    assert label == FAMILY
    assert 's32 list_head(void);' in changed
    assert 'node = (void *) list_head();' in changed
    assert 'check_mode:\n    current = (void *) mode;\n    if (current != 0)' in changed


def test_requires_both_slot_differences_and_an_explicit_no_input_definition():
    assert not variants(SOURCE, 'visit', ROWS[:6], '', CALLEES)
    assert not variants(SOURCE, 'visit', ROWS, '', {})
    assert not variants(SOURCE, 'visit', ROWS, '', {'list_head': GETTER.replace('(void)', '(int input)')})
    assert not variants(SOURCE, 'visit', ROWS, '', {'list_head': GETTER.replace('return root;', 'return some();')})
    assert not variants(SOURCE, 'visit', ROWS, 'extern void *list_head(s8);', CALLEES)


def test_requires_plain_local_argument_and_dead_pointer_on_both_join_paths():
    assert not variants(SOURCE.replace('list_head(port)', 'list_head(advance())'), 'visit', ROWS, '', CALLEES)
    assert not variants(SOURCE.replace('s32 port;', 'volatile s32 port;'), 'visit', ROWS, '', CALLEES)
    assert not variants(SOURCE.replace('    current = NULL;\n    report', '    report'),
                        'visit', ROWS, '', CALLEES)
    assert not variants(SOURCE.replace('        mode = 1;', '        mode = 2;', 1), 'visit', ROWS, '', CALLEES)
    assert not variants(SOURCE.replace('    check_mode:', '    escape(&current);\n    check_mode:'),
                        'visit', ROWS, '', CALLEES)
