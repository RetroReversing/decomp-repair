"""reload_temp_inline: locals that cache a plain memory read, written as the read where it is used.

From a 222-instruction stream refill built by IDO 7.1 (555 -> 60 with the three loop-head temporaries gone, then 0 with
`guard_prefix_while`). Checked on a small function of the same shape, never on game code."""
from decomprepair import registry
from decomprepair.reload_temp_inline import FAMILY, variants

SOURCE = '''void drain(Ring *p, s32 budget)
{
  u32 s1, s2, v1;
  s1 = p->head;
  v1 = s1 - p->tail;
  s2 = p->size;
  while (v1 < s2 - 0xA0 && budget > 0)
  {
    step(p, p->ring + ((s1 % s2) >> 2) * 8);
    p->head += 0xA0;
    s1 = p->head;
    v1 = s1 - p->tail;
    s2 = p->size;
    budget--;
  }
  if (p->mode == 1 && v1 >= s2 - 0x140)
  {
    p->mode = 2;
  }
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'drain') if family == FAMILY]


def test_every_cached_read_is_one_child_and_all_of_them_together_is_the_last():
    *single, everything = children()
    assert len(single) == 3
    assert 'u32' not in everything and 's1' not in everything and 's2' not in everything and 'v1' not in everything
    assert 'while ((p->head - p->tail) < p->size - 0xA0 && budget > 0)' in everything
    assert 'step(p, p->ring + ((p->head % p->size) >> 2) * 8);' in everything
    assert 'if (p->mode == 1 && (p->head - p->tail) >= p->size - 0x140)' in everything


def test_a_single_child_keeps_the_other_temporaries_and_the_declaration_of_them():
    first = children()[0]
    assert 'u32 s2, v1;' in first and 'v1 = p->head - p->tail;' in first


def test_a_use_after_a_store_is_left_alone():
    source = SOURCE.replace('    step(p, p->ring + ((s1 % s2) >> 2) * 8);\n    p->head += 0xA0;\n',
                            '    p->head += 0xA0;\n    step(p, p->ring + ((s1 % s2) >> 2) * 8);\n')
    (only,) = children(source)
    assert '(s1 % s2)' in only and 's1 = p->head;' in only and 'v1' not in only


def test_a_loop_test_that_the_body_does_not_recompute_is_left_alone():
    source = SOURCE.replace('    s1 = p->head;\n    v1 = s1 - p->tail;\n    s2 = p->size;\n    budget--;', '    budget--;')
    assert 'while ((p->head - p->tail)' not in ''.join(children(source))


def test_a_loop_with_a_continue_is_left_alone():
    source = SOURCE.replace('    budget--;\n', '    if (budget == 3)\n    {\n      continue;\n    }\n    budget--;\n')
    assert children(source) == []


def test_a_local_that_is_assigned_another_way_is_left_alone():
    source = SOURCE.replace('    budget--;\n', '    s1 += 4;\n    budget--;\n')
    assert all('s1 = p->head;' in text for text in children(source))


def test_a_local_whose_address_is_taken_is_left_alone():
    source = SOURCE.replace('    budget--;\n', '    note(&s2);\n    budget--;\n')
    assert all('s2 = p->size;' in text for text in children(source))


def test_a_line_with_two_calls_is_left_alone():
    source = SOURCE.replace('step(p, p->ring + ((s1 % s2) >> 2) * 8);', 'step(p, probe(p) + s1);')
    assert all('+ s1)' in text for text in children(source))


def test_a_name_the_read_depends_on_changing_in_between_blocks_it():
    source = SOURCE.replace('  s1 = p->head;\n  v1', '  s1 = q->head;\n  v1').replace('    s1 = p->head;\n    v1', '    s1 = q->head;\n    v1')
    source = source.replace('    budget--;\n', '    q = q->next;\n    budget--;\n').replace('(Ring *p, s32', '(Ring *p, Ring *q, s32')
    assert all('s1 = q->head;' in text for text in children(source))


def test_it_is_declared_for_the_callers():
    assert any(r.module == 'reload_temp_inline' for r in registry.declared())


HELPER = '''static inline unsigned int scaled(unsigned int value)
{
  return ((value >> 6) * 40U) + 256U;
}

void build(Voice *v, Cmd *c, u32 *run)
{
  s32 base;
  base = v->m2C;
  lookup(&c->m30, base + scaled(run[1]), run[5], base + 0x100);
}
'''


def test_a_call_to_a_pure_inline_helper_is_the_expression_not_a_second_call():
    # A 616-instruction audio command builder (KMC GCC 2.7.2): two such locals inlined took it from 60 to 0.
    children = [child for _, child in variants(HELPER, 'build')]
    assert any('lookup(&c->m30, v->m2C + scaled(run[1]), run[5], v->m2C + 0x100);' in c and 'base' not in c.split('build')[1]
               for c in children)


def test_a_helper_with_a_call_inside_still_counts_as_a_call():
    source = HELPER.replace('((value >> 6) * 40U) + 256U', 'other(value)')
    assert variants(source, 'build') == []
