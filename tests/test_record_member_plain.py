"""One-member records read through `->value`, written back as plain pointer casts."""
import re

from decomprepair.record_member_plain import variants

SOURCE = '''typedef struct { unsigned char pad[44]; f32 value; } Rec2C;
typedef struct { unsigned char pad[60]; int value; } Rec3C;
void f(void *a, void *b)
{
  D_1 = *((f32 *) (((char *) a) + 0x28));
  D_2 = ((Rec2C *) a)->value;
  ((Rec2C *) a)->value = 0;
  ((Rec3C *) b)->value = 1;
  g(((Rec3C *) b)->value + 1);
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == 'record_member_plain']


def test_every_site_of_a_record_is_written_plain_in_one_child():
    found = [_squash(text) for text in _all()]
    both_2c = [t for t in found if 'D_2 = *((f32 *) (((char *) a) + 0x2C));' in t and '*((f32 *) (((char *) a) + 0x2C)) = 0;' in t]
    assert both_2c and all('Rec2C *) a)->value' not in t for t in both_2c)
    assert any('->value = 1' in t for t in both_2c)  # the other record is untouched in that child


def test_all_records_at_once_and_single_sites_are_offered():
    found = [_squash(text) for text in _all()]
    assert any('->value' not in t.split('void f')[1] for t in found)
    singles = [t for t in found if t.split('void f')[1].count('->value') == 3]
    assert len(singles) >= 3


def test_the_pad_gives_the_byte_offset_and_a_record_without_pad_offset_zero():
    source = 'typedef struct { int value; } Rec0;\nvoid f(void *p)\n{\n  g(((Rec0 *) p)->value);\n}\n'
    assert any('g(*((int *) (((char *) p) + 0x0)));' in _squash(text) for text in _all(source))


def test_a_parenthesised_base_is_kept():
    source = 'typedef struct { unsigned char pad[8]; s16 value; } Rec8;\nvoid f(char *p)\n{\n  g(((Rec8 *) (p + 4))->value);\n}\n'
    assert any('g(*((s16 *) (((char *) (p + 4)) + 0x8)));' in _squash(text) for text in _all(source))


def test_nothing_to_do_without_a_record():
    assert variants('void f(void *p)\n{\n  g(*((int *) (((char *) p) + 4)));\n}\n', 'f') == []
    assert variants(SOURCE, 'missing') == []
