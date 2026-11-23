"""collapsed_guard_fence_inline: guard collapse, one-shot fence unwrap and an adjacent inline, as one child.

Synthetic shape of a 130-instruction KMC colour-update function (saved best 870; 2585 with the collapse alone, 1170
with the inline alone, 870 with the unwrap alone, 0 with all three). The inline's assignment shares its line with the
statement before it, as in m2c's `S; var = E;` lines."""
from decomprepair import collapsed_guard_fence_inline as c
from decomprepair import identical_arm_collapse_repairs, local_inline_repairs

SOURCE = '''extern u8 G;
extern u8 H;
u32 rnd(void);
void colour(void *arg0)
{
  s32 t;
  s32 r;
  u8 flag;
  u8 var_v0;
  u32 mode;
  mode = *((u32 *) (((char *) arg0) + 0x58));
  if (mode & 1)
  {
    do
    {
      *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x64)) = 0x40;
      *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x65)) = 0x40;
    }
    while (0);
    *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x66)) = 0x40;
    return;
  }
  if (mode & 2)
  {
    var_v0 = 8;
    *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x66)) = var_v0;
  }
  else
  {
    if (flag)
    {
      t = rnd();
      r = t / 3;
    }
    else
    {
      t = rnd();
      r = t / 3;
    }
    if (t == (r * 3))
    {
      *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x64)) = (u8) H;
      *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x65)) = (u8) H; var_v0 = G;
      *((u8 *) (((char *) (*((void **) (((char *) arg0) + 0x20)))) + 0x66)) = var_v0;
    }
  }
}
'''


def test_the_three_steps_are_one_child():
    out = c.variants(SOURCE, 'colour')
    assert out and all(family == 'collapsed_guard_fence_inline' for family, _ in out)
    text = out[0][1]
    assert 'if (flag)' not in text
    assert 'while (0)' not in text and 'do\n' not in text
    assert 'var_v0 = G' not in text and '= (G);' in text
    assert 'var_v0 = 8;' in text  # the arm that is not store-adjacent keeps its own local


def test_each_step_alone_is_not_the_combination():
    out = {t for _, t in c.variants(SOURCE, 'colour')}
    alone = [t for _, t in identical_arm_collapse_repairs.variants(SOURCE, 'colour')]
    assert alone and not out & set(alone)
    inline = [t for _, t in local_inline_repairs._adjacent(SOURCE, __import__('decomprepair.integer_repair_support', fromlist=['view']).view(SOURCE, 'colour'))]
    assert any('= (G);' in t for t in inline)  # a mid-line assignment is now inlined


def test_no_child_without_a_guard():
    plain = SOURCE.replace('if (flag)', 'if (t)')
    assert c.variants(plain.replace('    if (t)\n    {\n      t = rnd();\n      r = t / 3;\n    }\n    else\n    {\n      t = rnd();\n      r = t / 3;\n    }\n', '    t = rnd();\n    r = t / 3;\n'), 'colour') == []


def test_registered():
    assert c.REPAIR['variants'] is c.variants and c.FAMILY in c.REPAIR['families']
