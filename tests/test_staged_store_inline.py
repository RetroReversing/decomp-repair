"""A run of staged values and their stores, written as the direct stores."""
from decomprepair.staged_store_inline import variants

CODE = '''void f(S *a, S *b)
{
  s16 __repair_store_0;
  s16 __repair_store_1;
  int k;
  k = 3;
  __repair_store_0 = (s16) (*((u8 *) (((char *) b) + 0x36)));
  __repair_store_1 = (s16) (*((u8 *) (((char *) b) + 0x36)));
  *((s16 *) (((char *) a) + 0x176)) = __repair_store_0;
  *((s16 *) (((char *) a) + 0x176)) = __repair_store_1;
  g(k);
}
'''


def test_staged_values_are_stored_directly_and_their_declarations_go():
    [(family, child)] = variants(CODE, 'f')
    assert family == 'staged_store_inline'
    assert '__repair_store' not in child
    assert child.count('*((s16 *) (((char *) a) + 0x176)) = (s16) (*((u8 *) (((char *) b) + 0x36)));') == 2
    assert 'int k;' in child and 'k = 3;' in child


def test_a_staged_local_read_elsewhere_stays():
    assert variants(CODE.replace('g(k);', 'g(__repair_store_0);'), 'f') == []


def test_stores_in_another_order_do_not_inline_the_whole_run():
    swapped = CODE.replace('= __repair_store_0;', '= __repair_store_X;').replace('= __repair_store_1;', '= __repair_store_0;') \
                  .replace('= __repair_store_X;', '= __repair_store_1;')
    assert all('__repair_store_0' in child and '__repair_store_1' in child.split('{', 1)[1] or child.count('__repair_store') > 1
               for _, child in variants(swapped, 'f'))
    assert not any('__repair_store' not in child for _, child in variants(swapped, 'f'))
