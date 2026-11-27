"""A field stored back from a local that still holds it, written as the compound assignment."""
from decomprepair import copied_field_compound as m

Y = '*((s32 *) (((char *) arg0) + 0x1C))'
SPEED = '*((s32 *) (((char *) arg0) + 0x3C))'
PREV = '*((s32 *) (((char *) arg0) + 0x44))'


def source(between=None, load=None, store=None, pre='', post=''):
    between = between if between is not None else f'{SPEED} += 0x7A; }} while (0); {PREV} = temp_v1;'
    load = load or f'temp_v1 = {Y};'
    store = store or f'{Y} = (s32) (temp_v1 + ({SPEED}));'
    return f'''void f(void *arg0)
{{
  s32 temp_v1;
 do {{
  g(arg0);
  {pre}do {{ h(arg0); {load} {between} {post}
 }} while (0);
  {store}
  temp_v1 = *((s32 *) (((char *) arg0) + 0x34)) - 1;
}}
'''


def test_the_fenced_best_gets_the_compound_alone_and_with_its_fences_opened():
    # An SN64 GCC 2.8.1 object update: the saved best was 205; the child with the fences opened is exact.
    before = source()
    children = dict(m.variants(before, 'f'))
    alone = children['copied_field_compound']
    assert alone == before.replace(f'{Y} = (s32) (temp_v1 + ({SPEED}));', f'{Y} += ({SPEED});')
    opened = children['copied_field_compound_unfenced']
    assert 'do {' not in opened and f'{Y} += ({SPEED});' in opened and f'{PREV} = temp_v1;' in opened


def test_the_local_may_be_either_operand_of_a_commutative_operator_and_members_work():
    text = '''void f(P *p)
{
  s32 t;
  t = p->y;
  p->previous = t;
  p->y = p->speed + t;
}
'''
    assert m.variants(text, 'f') == [('copied_field_compound', text.replace('p->y = p->speed + t;', 'p->y += p->speed;'))]
    assert m.variants(text.replace('p->speed + t', 'p->speed - t'), 'f') == []
    (_, child), = m.variants(text.replace('p->speed + t', 't - p->speed'), 'f')
    assert 'p->y -= p->speed;' in child
    assert m.variants(text, 'f', 'union U { s32 y; s32 previous; };') == []


def test_left_alone_when_the_local_may_not_hold_the_field():
    unchanged = [
        source(between=f'{Y} = 0;', post='} while (0);'),
        source(between=f'{PREV} = temp_v1; temp_v1 = 4; }} while (0);'),
        source(between='k(arg0); } while (0);'),
        source(between='*((s32 *) (((char *) other) + 0x44)) = 0; } while (0);'),
        source(between='*((s16 *) (((char *) arg0) + 0x1E)) = 0; } while (0);'),
        source(between='arg0 = 0; } while (0);'),
        source(load=f'temp_v1 = {SPEED};'),
        source().replace(f'temp_v1 = {Y};', f'if (arg0) {{ temp_v1 = {Y}; }}'),
        source().replace('s32 temp_v1;', 'u16 temp_v1;'),
        source().replace('s32 *) (((char *) arg0) + 0x1C', 'volatile s32 *) (((char *) arg0) + 0x1C'),
    ]
    for text in unchanged:
        assert m.variants(text, 'f') == [], text
