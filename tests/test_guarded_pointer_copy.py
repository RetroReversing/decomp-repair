from decomprepair.guarded_pointer_copy import FAMILY, variants

SOURCE = """
extern int amount;
void f(void **record, int flag) {
    void *destination;
    void *entry;
    entry = record[0];
    if (entry != NULL) {
        amount += 1;
        *(int *)((char *)entry + 8) = amount;
        destination = record[1];
        *(int *)destination = 0;
    }
}
"""


def test_reuses_pointer_before_an_unconditional_overwrite():
    [(family, candidate)] = variants(SOURCE, 'f', arch='mips')
    assert family == FAMILY
    assert candidate == (SOURCE.replace('        amount += 1;', '        destination = entry;\n        amount += 1;')
                         .replace('(char *)entry + 8', '(char *)destination + 8'))


def test_only_offers_pointer_copy_with_a_proven_overwrite():
    for before, after in (
        ('        destination = record[1];', '        if (flag)\n            destination = record[1];'),
        ('        destination = record[1];', '        destination = flag ? destination : record[1];'),
        ('        amount += 1;', '        entry = record[2];'),
        ('        amount += 1;', '        expose(&destination);'),
        ('        amount += 1;', '        if (flag) goto after;'),
        ('    void *destination;', '    void *volatile destination;'),
    ):
        assert not variants(SOURCE.replace(before, after), 'f', arch='mips')
    assert not variants(SOURCE, 'f', arch='ppc')
