"""staged_store_first: `s = L + K; <pure locals>; L = s;` as `L = L + K; s = L; <pure locals>`.

From a 222-instruction stream refill built by IDO 7.1 (555 -> 300 as one step of a chain that reached 0 with
`reload_temp_inline` and `guard_prefix_while`). Checked on a small function of the same shape, never on game code."""
from decomprepair import registry
from decomprepair.staged_store_first import FAMILY, variants

SOURCE = '''typedef struct Ring
{
  u32 head;
  u32 tail;
  u16 size;
} Ring;
void drain(Ring *p, s32 budget)
{
  u32 s1, v1;
  u32 s2;
  while (budget > 0)
  {
    step(p);
    s1 = p->head + 0xA0;
    s2 = p->size;
    v1 = s1 - p->tail;
    p->head = s1;
    budget--;
  }
}
'''


def children(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'drain', header) if family == FAMILY]


def test_the_store_comes_first_and_the_local_is_read_back_from_the_field():
    (text,) = children()
    assert '    p->head = p->head + 0xA0;\n    s1 = p->head;\n    s2 = p->size;\n    v1 = s1 - p->tail;\n    budget--;' in text
    assert text.count('p->head = ') == 1


def test_a_line_between_that_names_the_field_blocks_it():
    assert children(SOURCE.replace('v1 = s1 - p->tail;', 'v1 = s1 - p->head;')) == []


def test_a_line_between_that_stores_or_calls_blocks_it():
    assert children(SOURCE.replace('s2 = p->size;', 's2 = look(p);')) == []
    assert children(SOURCE.replace('s2 = p->size;', 'p->tail = 0;')) == []


def test_a_field_narrower_than_the_local_blocks_it():
    assert children(SOURCE.replace('u32 head;', 'u16 head;')) == []


def test_a_width_nobody_declares_blocks_it():
    assert children(SOURCE.replace('  u32 head;\n', '')) == []
    assert len(children(SOURCE.replace('  u32 head;\n', ''), header='typedef struct Q { u32 head; } Q;')) == 1


def test_a_store_right_after_the_definition_has_nothing_to_move_over():
    assert children(SOURCE.replace('    s2 = p->size;\n    v1 = s1 - p->tail;\n', '')) == []


def test_it_is_declared_for_the_callers():
    assert any(r.module == 'staged_store_first' for r in registry.declared())
