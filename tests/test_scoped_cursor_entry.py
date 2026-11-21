from decomprepair.scoped_cursor_entry import FAMILY, variants

SOURCE = '''void f(char *base) {
    u16 **cursor;
    char *item;
    cursor = (u16 **) (base + 0xC);
scan:
    item = (char *) (*cursor);
    if (accept(item)) return;
    cursor += 3;
    goto scan;
}'''
ASM = 'addiu $s2, $s7, 0xc\n.Lscan:\nlw $s1, 0($s2)\n'


def test_scopes_the_setup_and_leaves_the_backedge_after_it():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert child == SOURCE.replace('cursor = (u16 **) (base + 0xC);',
                                   'do { cursor = (u16 **) (base + 0xC); } while (0);')


def test_requires_the_label_backedge_and_target_cursor():
    assert not variants(SOURCE.replace('goto scan;', 'return;'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('0($s2)', '0($s3)'))
    assert not variants(SOURCE.replace('cursor =', 'if (base) cursor =', 1), 'f', 'mips', ASM)
