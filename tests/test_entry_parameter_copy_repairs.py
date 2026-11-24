from decomprepair.entry_parameter_copy_repairs import variants

SOURCE = """void render(Cam *arg0, s32 arg1) {
    f32 scale;
    do {
        scale = arg0->zoom;
        if (arg0->flags & 4) {
            use(arg1, scale);
        }
        use(arg1 * 2, scale);
    } while (0);
}
"""


def _copies(source, param='arg1'):
    return [c for family, c in variants(source, 'render') if family == 'entry_parameter_copy' and f'{param}_in)' in c]


def test_a_parameter_is_copied_into_a_local_after_the_first_statement():
    found = _copies(SOURCE)
    assert any('scale = arg0->zoom;\n  arg1 = arg1_in;' in c for c in found)
    assert all('s32 arg1_in)' in c and '  s32 arg1;' in c and 'use(arg1, scale)' in c for c in found)


def test_the_copy_is_offered_at_the_top_of_the_body_and_inside_the_wrapper():
    places = {c.index('arg1 = arg1_in;') for c in _copies(SOURCE)}
    assert len(places) == 3  # past the declarations, inside the do-while, after its first statement


def test_a_parameter_used_once_or_addressed_is_left_alone():
    once = SOURCE.replace('use(arg1 * 2, scale);', 'use(2, scale);')
    assert not _copies(once)
    addressed = SOURCE.replace('use(arg1, scale);', 'use(&arg1, scale);')
    assert not _copies(addressed)


def test_a_function_without_parameters_or_with_asm_gives_nothing():
    assert not variants('void f(void) { g(); }\n', 'f')
    assert not variants(SOURCE.replace('scale = arg0->zoom;', 'asm("nop");'), 'render')


def test_the_clobber_child_overwrites_the_parameter_after_the_copy():
    found = [c for family, c in variants(SOURCE, 'render') if family == 'entry_parameter_clobber' and 'arg1_in)' in c]
    assert found and all('arg1 = arg1_in;\n  arg1_in = 0;' in c and 's32 arg1_in)' in c for c in found)
    assert len({c.index('arg1_in = 0;') for c in found}) == 3  # the same three places as the plain copy


def test_the_clobber_child_runs_a_pointer_parameter_before_the_first_call():
    source = 'void *spawn(s32 a, void *b) {\n  void *o;\n  o = make(0x50);\n  use(o, b);\n  use2(o, b);\n  return o;\n}\n'
    found = [c for family, c in variants(source, 'spawn') if family == 'entry_parameter_clobber']
    assert any(c.index('b = b_in;') < c.index('make(0x50)') and 'b_in = 0;' in c for c in found)
    assert 'entry_parameter_clobber' in __import__('decomprepair.entry_parameter_copy_repairs', fromlist=['x']).FAMILIES


def test_a_function_pointer_local_is_a_declaration_and_the_copy_goes_below_it():
    source = ('void act(void *a, s32 b, s32 c) {\n  s32 (*fn)(void *);\n  s32 t;\n  t = b;\n'
              '  fn = table[c];\n  fn(a);\n  use(b, c);\n}\n')
    found = [c for family, c in variants(source, 'act') if family == 'entry_parameter_copy' and 'c_in)' in c]
    assert found
    assert all(c.index('s32 (*fn)(void *);') < c.index('c = c_in;') for c in found)


FIVE = """void gather(const void *a, const void *b, const void *c, void *d, void *e) {
  *(f32 *)((s8 *)d + 0) = *(const f32 *)((s8 *)a + 0);
  *(f32 *)((s8 *)d + 4) = *(const f32 *)((s8 *)a + 4);
  *(f32 *)((s8 *)d + 8) = *(const f32 *)((s8 *)a + 8);
  *(f32 *)((s8 *)e + 0) = *(const f32 *)((s8 *)a + 0);
  *(f32 *)((s8 *)e + 4) = *(const f32 *)((s8 *)b + 4);
}
"""


def test_the_fifth_parameter_is_offered_though_four_others_come_first():
    for family in ('entry_parameter_copy', 'entry_parameter_clobber'):
        found = [c for f, c in variants(FIVE, 'gather') if f == family and 'void *e_in' in c]
        # the copy after the three stores to `d`, where the target loads the stack-passed argument
        assert any(c.index('e = e_in;') > c.index('(s8 *)d + 8)') and c.index('e = e_in;') < c.index('(s8 *)e + 0)')
                   for c in found), family


def test_the_children_stay_bounded_and_every_parameter_keeps_its_first_places():
    found = variants(FIVE, 'gather')
    assert len(found) <= 48
    # b is read once and c never, so only a, d and e are offered
    assert {param for param in 'abcde' if any(f'{param} = {param}_in;' in c for f, c in found)} == set('ade')


def test_a_read_ahead_of_the_copy_keeps_the_parameters_own_name():
    found = [c for f, c in variants(FIVE, 'gather') if f == 'entry_parameter_copy' and 'void *d_in' in c]
    late = [c for c in found if '(s8 *)d_in + 0)' in c]
    assert late and all('(s8 *)d + 0)' not in c.split('d = d_in;')[0] for c in late)
