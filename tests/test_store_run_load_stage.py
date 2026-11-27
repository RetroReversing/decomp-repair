"""store_run_load_stage: a load at the end of a store run is read into a local ahead of the run.

Reduced from an SN64 GCC 2.8.1 N64 object-spawning function (120 -> 0 with two sites): the fence above each run opens
and the load goes between it and the literal stores."""
from decomprepair import store_run_load_stage as s

SEED = '''void f(void *arg0) {
    void *temp_v0;
    void *temp_v0_2;

    temp_v0 = alloc();
    if (temp_v0 != NULL) {
        do { M2C_FIELD(temp_v0, s32 *, 0x80) = (s32) M2C_FIELD(arg0, s32 *, 0x80); } while (0);
        M2C_FIELD(temp_v0, s8 *, 0x7A) = 2;
        M2C_FIELD(temp_v0, s8 *, 0x74) = 2;
        M2C_FIELD(temp_v0, s16 *, 0x6A) = (s16) (M2C_FIELD(arg0, u16 *, 0x6A) - 2);
    }
    temp_v0_2 = alloc();
    if (temp_v0_2 != NULL) {
        M2C_FIELD(temp_v0_2, s8 *, 0x7A) = 2;
        M2C_FIELD(temp_v0_2, s16 *, 0x6A) = (s16) (M2C_FIELD(arg0, u16 *, 0x6A) - 1);
    }
}
'''


def _texts(source=SEED):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_every_site_at_once_comes_first_then_each_alone():
    out = _texts()
    assert len(out) == 3
    both = out[0]
    assert both.count('temp_load = M2C_FIELD(arg0, u16 *, 0x6A);') == 2
    assert both.count('u16 temp_load;') == 1
    assert 'do {' not in both
    assert ('M2C_FIELD(temp_v0, s32 *, 0x80) = (s32) M2C_FIELD(arg0, s32 *, 0x80);\n'
            '        temp_load = M2C_FIELD(arg0, u16 *, 0x6A);\n'
            '        M2C_FIELD(temp_v0, s8 *, 0x7A) = 2;') in both
    assert '(s16) (temp_load - 2);' in both and '(s16) (temp_load - 1);' in both


def test_one_site_leaves_the_other_alone():
    one = _texts()[1]
    assert one.count('temp_load =') == 1 and '(M2C_FIELD(arg0, u16 *, 0x6A) - 1)' in one


def test_a_load_of_a_stored_offset_or_the_same_base_stays():
    same_offset = SEED.replace('0x7A) = 2;', '0x6A) = 2;').replace('0x74) = 2;', '0x6A) = 2;')
    assert not _texts(same_offset)
    assert not _texts(SEED.replace('M2C_FIELD(arg0, u16 *, 0x6A)', 'M2C_FIELD(temp_v0, u16 *, 0x6A)')
                      .replace('M2C_FIELD(temp_v0_2, s16', 'M2C_FIELD(temp_v0, s16'))


def test_a_run_with_a_call_stops_the_stage():
    assert len(_texts(SEED.replace('0x74) = 2;', '0x74) = g();'))) == 1


def test_two_loaded_types_get_two_locals():
    both = _texts(SEED.replace('(M2C_FIELD(arg0, u16 *, 0x6A) - 1)', '(M2C_FIELD(arg0, s16 *, 0x6A) - 1)'))[0]
    assert 'u16 temp_load;' in both and 's16 temp_load_s16;' in both
    assert 'temp_load_s16 = M2C_FIELD(arg0, s16 *, 0x6A);' in both
