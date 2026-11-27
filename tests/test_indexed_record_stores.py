"""Stores through `table[i].p`: one base spelling, offset order and the target's widths."""
from decomprepair import indexed_record_stores as m
from decomprepair import registry

SOURCE = '''void f(void) {
  unsigned dead;
  *((s32 *) T[i].p) = 0;
  *((s8 *) (((char *) T[i].p) + 9)) = 0;
  dead = i * 0x64;
  *((s8 *) (((char *) (T + i)->p) + 6)) = 0;
  *((s16 *) (((char *) (*(&T[i])).p) + 0xA)) = 0;
}
'''
ASM = '''sb $zero, 0x0($v0)
sb $zero, 0x6($v0)
sb $zero, 0x9($v0)
sh $zero, 0xA($v1)
sw $zero, 0x24($sp)
'''


def test_spelling_order_and_width_together():
    family, child = m.variants(SOURCE, 'f', ASM)[0]
    assert family == m.FAMILY
    body = [line.strip() for line in child.splitlines()]
    assert body[2:7] == ['*((s8 *) T[i].p) = 0;', '*((s8 *) (((char *) T[i].p) + 6)) = 0;', 'dead = i * 0x64;',
                         '*((s8 *) (((char *) T[i].p) + 9)) = 0;', '*((s16 *) (((char *) T[i].p) + 0xA)) = 0;']


def test_a_read_local_stops_the_run():
    source = SOURCE.replace('}\n', '  g(dead);\n}\n')
    assert '+ 9)) = 0;\n  dead = i * 0x64;' in m.variants(source, 'f')[-1][1]


def test_declared_to_the_registry():
    assert any(r.module == 'indexed_record_stores' for r in registry.declared())
