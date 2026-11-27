"""sum_before_store_run: the sum stored last in a run of stores is computed into a local before the run.

Reduced from a KMC N64 voice-stop function (305 -> 0): the two-store run's child is the matched source's order, and the
`do { } while (0)` wrappers of earlier drafts are looked through."""
from decomprepair import sum_before_store_run as s

PLAIN = '''void f(void *arg0, void *arg1) {
    void *temp_v0;

    temp_v0 = alloc();
    if (temp_v0 != NULL) {
        M2C_FIELD(temp_v0, s16 *, 8) = 0xF;
        M2C_FIELD(temp_v0, s32 *, 0) = 0;
        M2C_FIELD(temp_v0, s32 *, 4) = (s32) (M2C_FIELD(arg0, s32 *, 0x1C) + M2C_FIELD(M2C_FIELD(arg1, void **, 8), s32 *, 0xD8));
        send(temp_v0);
    }
}
'''


def _texts(source=PLAIN):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_full_run_gets_the_sum_first_and_the_local_stored():
    full = [t for t in _texts() if t.index('temp_sum =') < t.index('0xF;')][0]
    body = full[full.index('if (temp_v0'):]
    assert body.splitlines()[1].strip().startswith('temp_sum = M2C_FIELD(arg0, s32 *, 0x1C) + M2C_FIELD(')
    assert 'M2C_FIELD(temp_v0, s32 *, 4) = temp_sum;' in body
    assert '    s32 temp_sum;\n' in full


def test_shorter_run_is_its_own_child():
    assert len(_texts()) == 2


def test_wrappers_are_looked_through():
    wrapped = PLAIN.replace('M2C_FIELD(temp_v0, s32 *, 0) = 0;', 'do { M2C_FIELD(temp_v0, s32 *, 0) = 0; } while (0);')
    assert len(_texts(wrapped)) == 2


def test_a_sum_reading_the_stored_base_is_left_alone():
    assert _texts(PLAIN.replace('M2C_FIELD(arg0, s32 *, 0x1C)', 'M2C_FIELD(temp_v0, s32 *, 0x1C)')) == []


def test_a_call_in_the_run_stops_it():
    assert _texts(PLAIN.replace('M2C_FIELD(temp_v0, s32 *, 0) = 0;', 'M2C_FIELD(temp_v0, s32 *, 0) = g();')) == []
