from decomprepair import integer_first_call_address as first
from decomprepair import wide_pair_value as wide

ASM = '''
jal        func_80000100
nop
lui        $at, %hi(D_80001000)
sw         $v0, %lo(D_80001000)($at)
lui        $at, %hi(D_80001004)
sw         $v1, %lo(D_80001004)($at)
'''

SOURCE = '''extern s32 D_80001000;
extern u32 D_80001004;
void run(void)
{
  s32 t;
  set_time(0, 0);
  t = get_time();
  D_80001000 = t;
  (*(s32 *)&D_80001004) = t;
}
'''


def children(source, **kwargs):
    return dict(wide.variants(source, 'run', **kwargs))


def test_zero_pair_becomes_one_wide_argument():
    text = children(SOURCE)[wide.ARGUMENT]
    assert 'extern void set_time();' in text
    assert '((void (*)()) set_time)(0ULL);' in text


def test_declared_callee_is_only_cast():
    text = children(SOURCE, header='void set_time(s32, s32);')[wide.ARGUMENT]
    assert 'extern void set_time' not in text
    assert '((void (*)()) set_time)(0ULL);' in text


def test_odd_position_is_left_alone():
    assert wide.ARGUMENT not in children(SOURCE.replace('set_time(0, 0)', 'set_time(a, 0, 0)'))


def test_returned_pair_becomes_one_store():
    text = children(SOURCE, asm=ASM)[wide.RESULT]
    assert '*(unsigned long long *) &D_80001000 = ((unsigned long long (*)()) get_time)();' in text
    assert 'D_80001004) = t' not in text
    assert wide.RESULT not in children(SOURCE)


def test_integer_first_address():
    source = '''void run(u8 *base)
{
  s32 k;
  k = 4;
  g(k + base);
  g(base + k);
}
'''
    texts = [text for _, text in first.variants(source, 'run')]
    assert len(texts) == 2
    assert all('g((u8 *)(k + (int) base));' in text for text in texts)
