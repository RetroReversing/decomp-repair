from decomprepair.switch_case_tail_goto import FAMILY, variants

# The shape of an 874-instruction object spawner's inner switch (KMC GCC 2.7.2): several cases end with the flag set
# that a later case group consists of; the case that also updates a word must jump to that group (465 -> 15).
SOURCE = '''void f(Spawn *sp)
{
    s32 mode;
    s8 kind;

    kind = 0;
    switch (sp->type) {
        case 0x73:
            sp->flags |= 0x1000;
            kind = 1;
            break;
        case 0x79:
            mode = 3;
            kind = 1;
            break;
        case 0x5D:
            sp->flags |= 0x1000;
            break;
        case 0x30: case 0x54:
            kind = 1;
            break;
    }
    if (kind == 0) {
        g(mode);
    }
}
'''


def test_a_case_tail_that_repeats_a_whole_case_group_jumps_to_it():
    children = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    wanted = [t for t in children if 'sp->flags |= 0x1000;\n            goto shared_tail;' in t]
    assert wanted
    child = wanted[0]
    assert 'case 0x30: case 0x54:\n            shared_tail:\n            kind = 1;\n            break;' in child
    assert child.count('kind = 1;') == 2          # the other case keeps its own copy in this child
    # one child jumps from every such case at once
    assert any(t.count('goto shared_tail;') == 2 for t in children)


def test_a_case_with_nothing_but_the_shared_statement_or_a_compound_tail_is_left_alone():
    assert variants(SOURCE.replace('        case 0x30: case 0x54:\n            kind = 1;\n            break;\n', ''), 'f') == []
    braced = SOURCE.replace('            sp->flags |= 0x1000;\n            kind = 1;', '            if (sp) { kind = 1; }')
    assert all('if (sp) { goto' not in t for _, t in variants(braced, 'f'))


def test_an_existing_label_on_the_group_is_reused():
    labelled = SOURCE.replace('        case 0x30: case 0x54:\n            kind = 1;', '        case 0x30: case 0x54:\n        set_kind:\n            kind = 1;')
    children = [t for _, t in variants(labelled, 'f')]
    assert children and all('shared_tail' not in t for t in children)
    assert any('sp->flags |= 0x1000;\n            goto set_kind;' in t for t in children)
