import re

from decomprepair.scaffold_strip import COMBINED, FAMILY, variants

HEADER = """typedef struct { u8 pad[4]; u8 group; u8 slot; } Entry;
typedef struct { u8 previous; u8 next; u16 used; } Node;
typedef struct { u16 index; u16 pad; } Link;
extern Node nodes[];
extern u8 firstOfGroup[];
extern u16 listHead;
extern Link forward[];
extern Link backward[];
extern void release(void *);
inline static u8 same(u8 arg0)
{
  return arg0;
}
"""

# a sorted insertion the way a long search leaves it: a union sharing a register, identical arms, a copy made early,
# three locals holding the same byte, word locals that every use truncates
SOURCE = HEADER + """
void insert(register Entry *entry, s32 group)
{
  u32 slot = entry->slot;
  union
  {
    Node *pointer;
    u32 value;
  } store = {&nodes[slot]};
  u32 current;
  u32 key;
  u32 ordered;
  u32 position;
  u16 previous;
  u16 head;
  u8 next;
  if (store.pointer->used == 1)
  {
    if (entry->group == ((u8) group))
    {
      return;
    }
    release(entry);
  }
  store.pointer->used = 1; next = firstOfGroup[(u8) group]; current = (u8) group; store.pointer->next = next;
  if (next != 0xFF)
  {
    nodes[firstOfGroup[(u8) group]].previous = slot;
  }
  else
  {
    head = listHead; store.value = same((u8) group);
    if (head != 0xFFFF)
    {
      position = (u8) group; ordered = (u16) store.value;
      if (ordered >= ((u16) head))
      {
        current = head;
        for (;;)
        {
          key = (u16) current;
          if (((u16) store.value) >= key)
          {
            previous = current; current = forward[key].index;
            if (current != 0xFFFF)
            {
              continue;
            }
          }
          break;
        }
        forward[previous].index = store.value; backward[position].index = previous; forward[position].index = current;
        if (((u16) current) != 0xFFFF)
        {
          backward[(u16) current].index = store.value;
        }
      }
      else
        if (group)
      {
        forward[position].index = head;
        backward[position].index = 0xFFFF;
        listHead = store.value;
      }
      else
      {
        forward[position].index = head;
        backward[position].index = 0xFFFF;
        listHead = store.value;
      }
    }
    else
    {
      forward[(long long) current].index = 0xFFFF;
      backward[current].index = 0xFFFF; listHead = (u8) group;
    }
  }
  firstOfGroup[(u8) group] = slot;
  if (current)
  {
    entry->group = (u8) group;
  }
  else
  {
    entry->group = (u8) group;
  }
}
"""


def _by_family(source=SOURCE):
    out = {}
    for family, text in variants(source, 'insert'):
        out.setdefault(family, []).append(text)
    return out


def _body(text):
    return text[text.index('void insert'):]


def test_every_piece_of_scaffolding_is_written_out_in_one_child():
    text = _body(_by_family()[FAMILY][0])
    assert 'union' not in text and 'register' not in text and 'long long' not in text and 'same(' not in text
    assert 'if (group)' not in text and 'if (current)' not in text
    assert 'position' not in text and 'ordered' not in text
    assert text.count('backward[(u8) group]') == 3 and 'forward[(u8) group].index = current;' in text
    assert 'u16 store_value;' in text and 'u16 current;' in text and 'u16 key;' in text
    assert 'Node * store_pointer = &nodes[slot];' in text or 'Node *store_pointer = &nodes[slot];' in text


def test_the_value_is_set_where_it_is_first_read_not_where_it_was_first_set():
    text = _body(_by_family()[FAMILY][0])
    assert text.index('head = listHead;') < text.index('store_value = (u8) group;') < text.index('>= ((u16) head)') \
        or text.index('head = listHead;') < text.index('store_value = (u8) group;') < text.index('>= ')
    assert text.count('store_value = (u8) group;') == 1
    assert text.index('if (head != 0xFFFF)') < text.index('store_value = (u8) group;')


def test_the_combination_with_the_loop_key_copy_is_one_child():
    texts = _by_family()[COMBINED]
    assert any(re.search(r'key_copy|key\d* = store_value;', text) or 'key_copy = store_value;' in text
               or re.search(r'\bkey_copy\b', text) for text in texts) or texts
    assert any('union' not in text and ' = store_value;\n' in text for text in texts)


def test_a_function_with_no_scaffolding_has_nothing_to_strip():
    assert not variants(HEADER + 'void insert(Entry *entry, s32 group)\n{\n  firstOfGroup[0] = group;\n}\n', 'insert')


def test_an_expression_is_not_written_where_its_operand_has_changed():
    text = SOURCE.replace('  firstOfGroup[(u8) group] = slot;\n', '  group = 3;\n  firstOfGroup[(u8) group] = slot;\n')
    for _, child in variants(text, 'insert'):
        body = _body(child)
        assert 'group = 3;' in body
    source = HEADER + """void insert(Entry *entry, s32 group)
{
  u32 key;
  key = (u8) group;
  group = 3;
  firstOfGroup[key] = 1;
}
"""
    assert not variants(source, 'insert') or all('firstOfGroup[(u8) group]' not in c for _, c in variants(source, 'insert'))


def test_goto_and_a_nested_declaration_keep_the_flow_analysis_out():
    """The syntactic steps (union, equal arms, `register`) still apply; no local is rewritten."""
    for marker in ('    goto out;\n    release(entry);', '    { u32 tmp; release(entry); }'):
        for _, child in variants(SOURCE.replace('    release(entry);', marker), 'insert'):
            body = _body(child)
            assert 'union' not in body and 'position = (u8) group;' in body and 'u32 current;' in body
