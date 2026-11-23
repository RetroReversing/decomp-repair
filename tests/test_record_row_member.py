"""Fields of fixed-size records in an owner, written as record members (a 1300-instruction routine, 75 -> 65)."""
from decomprepair.record_row_member import FAMILY, REPAIR, variants

SOURCE = """void track(void *arg0, void *temp_s1, s32 n)
{
  *((f32 *) (((char *) (temp_s1 + (n * 8))) + 0x200)) = 1.0f;
  *((s8 *) (((char *) (temp_s1 + ((n - 1) * 8))) + 0x1FE)) = (s8) n;
}
"""


def test_both_sites_become_members_of_one_record_type():
    [(family, child)] = variants(SOURCE, 'track')
    assert family == FAMILY
    assert '  u8 head[0x1FC];\n  Row8_temp_s1 rec[1];\n} Rows8_temp_s1;' in child
    assert '  s8 f2;' in child and '  f32 f4;' in child
    assert '((Rows8_temp_s1 *) temp_s1)->rec[n].f4 = 1.0f;' in child
    assert '((Rows8_temp_s1 *) temp_s1)->rec[(n - 1)].f2 = (s8) n;' in child
    assert child.index('typedef struct') < child.index('void track(')


def test_fields_that_do_not_fit_one_record_are_left_alone():
    assert variants(SOURCE.replace('+ 0x1FE', '+ 0x1F0'), 'track') == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['families'] == (FAMILY,)
