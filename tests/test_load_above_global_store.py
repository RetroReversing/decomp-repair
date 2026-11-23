"""A pointer loaded by the statement after a global store, loaded before the store."""
import re

from decomprepair.load_above_global_store import variants

CODE = '''extern s32 gFlags;
extern s32 gMode;
void f(void *arg0, char *def)
{
  s32 k;
  gFlags |= 0x10000;
  gMode = (s32) (*((u8 *) inline_fn2((char *) def, 0x5E)));
  k = *((s8 *) inline_fn2((char *) (*((void **) inline_fn2((char *) arg0, 0x68))), 0xE));
  g(k);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_pointer_read_moves_above_the_store_just_before_its_statement():
    [(family, child)] = variants(CODE, 'f')
    assert family == 'load_above_global_store'
    text = squash(child)
    assert 'void *held0;' in text
    assert text.index('held0 = *((void **) inline_fn2((char *) arg0, 0x68));') < text.index('gMode =')
    assert text.index('gFlags |=') < text.index('held0 =')
    assert 'inline_fn2((char *) (held0), 0xE)' in text


def test_a_call_in_the_store_or_a_base_the_store_reads_is_left_alone():
    assert variants(CODE.replace('gMode = (s32)', 'gMode = h((s32)'), 'f') == []
    assert variants(CODE.replace('(char *) def, 0x5E', '(char *) arg0, 0x5E'), 'f') == []


def test_a_store_to_a_local_is_not_a_global_store():
    assert variants(CODE.replace('gMode =', 'k ='), 'f') == []
