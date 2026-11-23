from decomprepair import volatile_operand_hoist as r

SOURCE = '''extern void format(void *, void *, int);
inline static int scaled(volatile u8 *p)
{
  return (*p) * 0x18;
}

void f(void *dst, void *src)
{
  volatile u8 *base;
  int off;

  format(dst, src, 0);
  off = ((int) base) - 0x109;
  format(dst, src, scaled(base) + off);
}
'''


def children(source=SOURCE):
    return [text for fam, text in r.variants(source, 'f') if fam == 'volatile_operand_hoist']


def test_the_volatile_read_is_held_in_a_local_ahead_of_the_neighbouring_assignment():
    out = children()
    assert len(out) == 1
    child = out[0]
    assert 'int __repair_volatile_read;' in child
    assert child.index('__repair_volatile_read = scaled(base);') < child.index('off = ((int) base) - 0x109;')
    assert 'format(dst, src, __repair_volatile_read + off);' in child


def test_an_assignment_that_reads_a_volatile_object_is_left_alone():
    assert children(SOURCE.replace('((int) base) - 0x109', '(*base) - 0x109')) == []


def test_a_read_of_a_non_volatile_pointer_is_left_alone():
    assert children(SOURCE.replace('volatile u8 *base;', 'u8 *base;')) == []


def test_a_sum_with_another_local_is_left_alone():
    assert children(SOURCE.replace('scaled(base) + off', 'scaled(base) + 4')) == []
