"""A block's own temporary written as a function-level local the block does not otherwise use."""
from decomprepair.block_temp_role_merge import FAMILY, variants

# Two table passes of a bit-stream decoder (KMC GCC 2.7.2, N64): the second pass's loaded code has a name of its own,
# where the original reused the function's working variable `a`.
PASSES = '''void f(u32 *t, u16 *tab, u32 n)
{
  u32 a;
  u32 k;
  a = t[0];
  tab[0] = a;
  k = 0;
  do {
    u32 cd = t[k];
    u16 ent = tab[cd & 7];
    tab[k] = ent + cd;
    k++;
  } while (k < n);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_temporary_becomes_the_free_function_local_and_later_initialisers_split():
    want = PASSES.replace('''    u32 cd = t[k];
    u16 ent = tab[cd & 7];
    tab[k] = ent + cd;''', '''    u16 ent;
    a = t[k];
    ent = tab[a & 7];
    tab[k] = ent + a;''')
    assert want in _children(PASSES)


def test_a_survivor_read_after_the_block_is_left_alone():
    text = PASSES.replace('  } while (k < n);\n', '  } while (k < n);\n  tab[1] = a;\n')
    assert not any('a = t[k];' in src for src in _children(text))


def test_a_survivor_the_block_mentions_is_left_alone():
    text = PASSES.replace('    tab[k] = ent + cd;', '    tab[k] = ent + cd + a;')
    assert not any('a = t[k];' in src for src in _children(text))


def test_a_survivor_a_macro_mentions_is_left_alone():
    assert not any('a = t[k];' in src for src in _children('#define GET(d) d = a\n' + PASSES))


def test_a_bare_declaration_set_first_is_offered_too():
    # the decoder's scatter index, declared bare and set as the block's first use of it (215 -> 110 needed it as `y`)
    text = PASSES.replace('    u32 cd = t[k];\n', '    u32 cd;\n    cd = t[k];\n')
    children = _children(text)
    assert any('    a = t[k];\n' in src and 'cd' not in src for src in children)


def test_a_bare_declaration_read_before_it_is_set_is_left_alone():
    text = PASSES.replace('    u32 cd = t[k];\n', '    u32 cd;\n    tab[1] = cd;\n    cd = t[k];\n')
    assert not any('cd' not in src for src in _children(text))
