"""The pointer-chain load pinned behind the branch operand's load: proposals only, nothing is compiled here."""
from decomprepair.chain_load_scope import COLLAPSE, FAMILY, variants

# The shape of a menu-update function (GCC 2.7.2, KMC, N64) at 210 with one row wrong: the target read the branch
# operand's global pointer ahead of the chain's last load. m2c wrote the chain twice, in identical arms.
BEFORE = '''extern void *gState;
extern s32 sink(s32);
void f(void)
{
  void *entry;
  s32 value;
  void *next;
  entry = *((void **) (((char *) gState) + 0x18));
  if (entry)
  {
    value = *(*((s32 **) (((char *) entry) + 0x10)));
    next = entry + 0x28;
  }
  else
  {
    value = *(*((s32 **) (((char *) entry) + 0x10)));
    next = entry + 0x28;
  }
  if (((*((u8 *) (((char *) gState) + 0x2D))) != 0) && ((*((u8 *) (((char *) gState) + 0x2E))) == 0))
  {
    sink(value);
  }
  sink(next);
}
'''
COLLAPSED = '''  value = *(*((s32 **) (((char *) entry) + 0x10)));
  next = entry + 0x28;
  if (((*((u8 *)'''
MATCHED_SHAPE = '''  chain_ptr = *((s32 **) (((char *) entry) + 0x10));
  guard_load = (*((u8 *) (((char *) gState) + 0x2D)));
  do { value = *chain_ptr; } while (0);
  next = entry + 0x28;
  if ((guard_load != 0) && ((*((u8 *) (((char *) gState) + 0x2E))) == 0))'''


def test_identical_arms_are_written_once_alone_and_with_the_scope():
    found = variants(BEFORE, 'f')
    assert any(family == COLLAPSE and COLLAPSED in text and 'else' not in text.split('sink(value)')[0]
               for family, text in found)
    scoped = [text for family, text in found if family == FAMILY]
    assert scoped and all(MATCHED_SHAPE in text for text in scoped)
    assert any('if (entry)' not in text for text in scoped)  # arms collapsed first: the combination


def test_the_scope_declares_its_locals_once_and_keeps_the_chain_type():
    scoped = [text for family, text in variants(BEFORE, 'f') if family == FAMILY][0]
    assert scoped.count('s32 *chain_ptr;') == 1 and scoped.count('u8 guard_load;') == 1


def test_nothing_is_proposed_when_the_branch_reads_the_chain_value_or_calls():
    reads = BEFORE.replace('(*((u8 *) (((char *) gState) + 0x2D)))', 'sink(value)')
    assert not [1 for family, _ in variants(reads, 'f') if family == FAMILY]
    effect = BEFORE.replace('  next = entry + 0x28;\n  }\n  else', '  next = sink(1);\n  }\n  else')
    assert not [1 for family, text in variants(effect, 'f') if family == COLLAPSE and 'else' not in text]


def test_only_mips_is_proposed():
    assert variants(BEFORE, 'f', 'ppc') == []


def test_distinct_arms_are_left_alone():
    differ = BEFORE.replace('next = entry + 0x28;\n  }\n  else', 'next = entry + 0x30;\n  }\n  else')
    assert not [1 for family, _ in variants(differ, 'f') if family == COLLAPSE]
