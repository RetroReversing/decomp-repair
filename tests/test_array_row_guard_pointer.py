from decomprepair import registry
from decomprepair.array_row_guard_pointer import variants

SOURCE = '''
typedef unsigned short u16;
void f(int c, int i) {
    u16 (*row)[8];
    row = get_row();
    if (row[c][i] == 0xFFFF) {
        return;
    }
    use(row[(unsigned char)c][i]);
}
'''


def test_stages_the_row_only_for_the_guard():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'u16 *__repair_guard_row;' in children[0][1]
    assert '__repair_guard_row = row[c];\n    if (__repair_guard_row[i] == 0xFFFF)' in children[0][1]
    assert 'row[(unsigned char)c][i]' in children[0][1]
    assert any(item.module.endswith('array_row_guard_pointer') for item in registry.declared())


def test_declines_effectful_or_conditional_guards():
    assert not variants(SOURCE.replace('row[c][i]', 'row[c++][i]'), 'f')
    assert not variants(SOURCE.replace('    if (row[c][i]', '    if (c)\n    if (row[c][i]'), 'f')
    assert not variants(SOURCE.replace('u16 (*row)[8];', 'volatile u16 (*row)[8];'), 'f')
    assert not variants(SOURCE.replace('    if (row[c][i]', '    { unsigned char row[4][8]; use(row); }\n    if (row[c][i]'), 'f')
    assert variants(SOURCE, 'f', header='extern volatile int status;')
    assert not variants(SOURCE, 'f', flags=['-Drow=other'])
    assert not variants(SOURCE, 'f', header='#include "unknown.h"')
