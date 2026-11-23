"""A load-and-store scope with other statements inside it, opened after them."""
import re

from decomprepair.block_extract_sink import variants

CODE = '''void f(char *marker, int arg1, char *table)
{
  int kind;
  {
    f32 yaw = *((f32 *) (marker + 0x34));
    cameraAngles[0] = yaw;
    {
      f32 pitch = *((f32 *) (marker + 0x38));
      var_s6 = 1;
      sp37 = arg1;
      cameraAngles[1] = pitch;
    }
    temp_s4 = ((char *) (&table)) + (kind * 0xE8);
  }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def families(text):
    return [squash(child) for family, child in variants(text, 'f') if family == 'block_extract_sink']


def test_the_assignments_go_above_and_the_scope_below_what_follows_as_one_child():
    both = [c for c in families(CODE) if c.index('var_s6 = 1;') < c.index('f32 pitch')]
    assert any('cameraAngles[0] = yaw; var_s6 = 1; sp37 = arg1; temp_s4 = ((char *) (&table)) + (kind * 0xE8); '
               '{ f32 pitch = *((f32 *) (marker + 0x38)); cameraAngles[1] = pitch; } }' in c for c in both)


def test_each_half_is_offered_alone_too():
    found = families(CODE)
    assert len(found) == 3
    assert any('temp_s4 = ((char *) (&table)) + (kind * 0xE8); { f32 pitch = *((f32 *) (marker + 0x38)); '
               'var_s6 = 1; sp37 = arg1; cameraAngles[1] = pitch; } }' in c for c in found)
    assert any('var_s6 = 1; sp37 = arg1; { f32 pitch' in c and 'temp_s4' in c.split('cameraAngles[1]')[1] for c in found)


def test_a_dereference_between_the_scope_and_its_store_is_not_lifted():
    assert families(CODE.replace('var_s6 = 1;', 'var_s6 = *p;')) == [] or all(
        'var_s6 = *p; sp37' not in c.split('{ f32 pitch')[0] for c in families(CODE.replace('var_s6 = 1;', 'var_s6 = *p;')))


def test_a_statement_after_the_scope_that_reads_the_local_stays_after():
    code = CODE.replace('(kind * 0xE8)', '(kind * 0xE8) + (int) pitch')
    assert not any('temp_s4' in c.split('{ f32 pitch')[0] for c in families(code))


def test_other_processors_are_not_offered_it():
    assert variants(CODE, 'f', 'ppc') == []
