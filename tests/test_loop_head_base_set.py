"""A global array's address set at the top of the loop that reads it (an N64 list walk, 115 -> 0)."""
from decomprepair.loop_head_base_set import FAMILY, variants

HEAD = "extern u16 D_8011F068[];\nextern u8 D_8011F2F0[];\n\n"
WANTED = '''void walk(void)
{
    u16 i;
    u16 *tab;

    i = 0;
    while (D_8011F068[i] != 0xFFFF) {
        tab = D_8011F068;
        use(tab[i]);
        i++;
    }
}
'''


def _only(source):
    found = variants(HEAD + source, 'walk')
    assert [family for family, _ in found] == [FAMILY]
    return found[0][1]


def test_a_set_inside_the_condition_moves_to_the_top_of_the_body():
    source = WANTED.replace('while (D_8011F068[i]', 'while ((tab = D_8011F068)[i]').replace('        tab = D_8011F068;\n', '')
    assert _only(source) == HEAD + WANTED


def test_a_set_before_the_loop_and_at_its_end():
    source = WANTED.replace('        tab = D_8011F068;\n', '').replace('    while', '    tab = D_8011F068;\n    while')
    source = source.replace('        i++;\n', '        i++;\n        tab = D_8011F068;\n')
    assert _only(source) == HEAD + WANTED


def test_a_condition_that_reads_the_local_reads_the_array():
    source = WANTED.replace('while (D_8011F068[i]', 'while (tab = D_8011F068, tab[i]').replace('        tab = D_8011F068;\n', '')
    assert _only(source) == HEAD + WANTED


def test_a_do_loop():
    source = '''void walk(void)
{
    u16 i;
    u16 *tab;

    i = 0;
    tab = D_8011F068;
    do {
        use(tab[i]);
        i++;
    } while (tab[i] != 0xFFFF);
}
'''
    child = _only(source)
    assert '    do {\n        tab = D_8011F068;\n        use(tab[i]);' in child
    assert '} while (D_8011F068[i] != 0xFFFF);' in child


def test_a_use_after_the_loop_another_value_or_a_step_is_left_alone():
    source = WANTED.replace('        tab = D_8011F068;\n', '').replace('    while', '    tab = D_8011F068;\n    while')
    assert variants(HEAD + source, 'walk')
    assert variants(HEAD + source.replace('        i++;\n    }\n', '        i++;\n    }\n    use(tab[0]);\n'), 'walk') == []
    assert variants(HEAD + source.replace('        i++;\n', '        i++;\n        tab++;\n'), 'walk') == []
    assert variants(HEAD + source.replace('        i++;\n', '        i++;\n        tab = (u16 *) D_8011F2F0;\n'), 'walk') == []
    assert variants(HEAD + source.replace('        i++;\n', '        i++;\n        bump(&tab);\n'), 'walk') == []


def test_the_wanted_shape_has_no_child():
    assert variants(HEAD + WANTED, 'walk') == []
