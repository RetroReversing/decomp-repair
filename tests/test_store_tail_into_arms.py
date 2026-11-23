from decomprepair import store_tail_into_arms as r

THREE = '''typedef struct { s32 word; u8 level; } Rec;
extern Rec *gRec;
extern s32 gTable[];
extern s32 D_A;
extern s32 D_B;

void f(s32 idx, s32 flags)
{
  Rec *sound;
  s32 var_v0;
  s32 var_a0;

  if (idx != 0)
  {
    sound = gRec;
    var_v0 = gTable[idx];
    var_a0 = 7;
  }
  else
  {
    if (flags & 0x80)
    {
      sound = gRec;
      var_v0 = D_A;
    }
    else
    {
      sound = gRec;
      var_v0 = D_B;
    }
    var_a0 = sound->level;
  }
  sound->word = (var_v0 & (~0xFF)) | var_a0;
}
'''


def children(source, name='f'):
    return [text for fam, text in r.variants(source, name) if fam == 'store_tail_into_arms']


def test_the_store_is_written_in_each_leaf_with_its_own_values():
    values, everything = children(THREE)
    assert values.count('sound->word = ') == 3
    assert 'sound->word = (var_v0_1 & (~0xFF)) | var_a0_1;' in values
    assert 'sound->word = (var_v0_2 & (~0xFF)) | var_a0_2;' in values
    assert 'sound->word = (var_v0_3 & (~0xFF)) | var_a0_3;' in values
    # the nested arms' own trailing byte read moved into both of its leaves, ahead of the store
    assert values.count('var_a0_2 = sound->level;') == 1 and values.count('var_a0_3 = sound->level;') == 1
    assert values.index('var_a0_2 = sound->level;') < values.index('sound->word = (var_v0_2')
    # the record pointer the arms share keeps its one name in the first child, and gets one per leaf in the second
    assert 'Rec *sound_1;' in everything and 'Rec *sound;' in values
    assert 'var_v0 = ' not in values and 'var_a0 = ' not in values


def test_an_identical_arm_tail_is_written_once_in_each_leaf():
    source = THREE.replace('  sound->word = (var_v0 & (~0xFF)) | var_a0;\n',
                           '  if (flags)\n  {\n    sound->word = (var_v0 & (~0xFF)) | var_a0;\n  }\n  else\n  {\n'
                           '    sound->word = (var_v0 & (~0xFF)) | var_a0;\n  }\n')
    values = children(source)[0]
    assert values.count('sound->word = ') == 3 and 'if (flags)' not in values


def test_a_variable_read_after_the_store_is_left_alone():
    source = THREE.replace('  sound->word = (var_v0 & (~0xFF)) | var_a0;\n}',
                           '  sound->word = (var_v0 & (~0xFF)) | var_a0;\n  D_A = var_a0;\n}')
    for text in children(source):
        assert 'var_a0_1' not in text


def test_an_arm_that_does_not_set_a_variable_before_the_store_leaves_it_alone():
    source = THREE.replace('    var_v0 = gTable[idx];\n', '')
    for text in children(source):
        assert 'var_v0_1' not in text


def test_a_variable_in_a_condition_is_left_alone():
    source = THREE.replace('if (flags & 0x80)', 'if (var_a0 & 0x80)').replace('  if (idx != 0)\n  {\n', '  var_a0 = 1;\n  if (idx != 0)\n  {\n')
    for text in children(source):
        assert 'var_a0_1' not in text


def test_a_tail_that_reads_nothing_the_arms_own_is_not_copied():
    source = THREE.replace('  sound->word = (var_v0 & (~0xFF)) | var_a0;\n', '  D_A = 1;\n')
    for text in children(source):
        assert text.count('D_A = 1;') == 1  # (only the nested chain's own tail, the byte read, was copied)
