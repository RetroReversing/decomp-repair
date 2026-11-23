from decomprepair import float_clamp_flip_pin as r

LOOP = '''typedef struct { f32 opacity; u32 alpha; } View;
extern View *sTable[];
extern void touch(View *);

void f(void)
{
  f32 opacity;
  u32 i;
  i = 0;
  do
  {
    View *view = sTable[i];
    opacity = (view->opacity > 0.0f) ? (view->opacity) : (0.0f);
    view->alpha = (u32) (opacity * 255.0f);
    touch(view);
    i += 1;
  }
  while (i < 6);
}
'''


def test_the_clamp_is_flipped_with_its_zero_pinned_in_one_child():
    out = [text for fam, text in r.variants(LOOP, 'f') if fam == 'float_clamp_flip_pin']
    assert len(out) == 1
    child = out[0]
    assert 'f32 __repair_zero;' in child
    assert 'opacity = view->opacity;' in child
    assert 'if (opacity < (__repair_zero = 0.0f))' in child
    assert 'opacity = __repair_zero;' in child
    assert '?' not in child


def test_a_clamp_outside_a_loop_is_left_alone():
    source = LOOP.replace('  do\n  {', '  {').replace('  }\n  while (i < 6);', '  }')
    assert not r.variants(source, 'f')


def test_a_clamp_of_something_else_is_left_alone():
    source = LOOP.replace('(view->opacity) : (0.0f)', '(view->alpha) : (0.0f)')
    assert not r.variants(source, 'f')


def test_the_name_is_not_taken_twice():
    child = r.variants(LOOP.replace('f32 opacity;', 'f32 opacity;\n  f32 __repair_zero;'), 'f')[0][1]
    assert 'f32 __repair_zero_;' in child
