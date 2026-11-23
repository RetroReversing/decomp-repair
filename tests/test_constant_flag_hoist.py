from decomprepair.constant_flag_hoist import FAMILIES, REPAIR, variants

SOURCE = """void run(int *table, int on)
{
  int flag;
  int sum;
  int i = 0;
  do {
    sum = 0;
    if (table[i] == 2 || probe(i)) {
      sum = table[i];
    }
    sum += on;
    if (on) flag = 1; else if (!on) flag = 1; else flag = 0;
    if (!flag) goto next;
    table[i] = sum;
    next: ;
    i++;
  } while (table[i] != -1);
}
"""


def test_the_flag_chain_moves_ahead_of_the_first_test_of_its_block():
    (family, text), = variants(SOURCE, 'run')
    assert family == 'constant_flag_hoist'
    lines = [line.strip() for line in text.splitlines()]
    assert lines.index('if (on) flag = 1; else if (!on) flag = 1; else flag = 0;') < lines.index('if (table[i] == 2 || probe(i)) {')
    assert text.count('else if (!on) flag = 1') == 1
    assert '    if (!flag) goto next;' in text  # the test and its indentation stay where they were


def test_a_chain_whose_arms_differ_is_left_alone():
    source = SOURCE.replace('else if (!on) flag = 1;', 'else if (!on) flag = 2;')
    assert variants(source, 'run') == []


def test_a_flag_read_between_the_new_place_and_the_old_one_stays():
    source = SOURCE.replace('    sum += on;', '    sum += flag;')
    assert variants(source, 'run') == []


def test_the_module_declares_itself():
    assert REPAIR['families'] == FAMILIES and REPAIR['variants'] is variants
