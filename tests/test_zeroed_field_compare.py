"""zeroed_field_compare: a zero test of a limit becomes the comparison with the counter just cleared."""
from decomprepair import registry
from decomprepair import zeroed_field_compare as zeroed

CHAINED = '''void f(void *arg0) {
    M2C_FIELD(arg0, u8 *, 0x10) = 0U;
    M2C_FIELD(arg0, s8 *, 0x11) = 0;
    if (((u8) M2C_FIELD(arg0, u8 *, 0x10) >= (u8) M2C_FIELD(&gLimits, u8 *, 0)) && (M2C_FIELD(&gLimits, u8 *, 1) == 0)) {
        spawn(arg0);
    }
}
'''

GUARDS = '''typedef struct {
    u8 first;
    u8 second;
} Limits;
extern Limits gLimits;
void f(Obj *self) {
    self->done = 0;
    self->made = 0;
    if (self->done < gLimits.first) {
        return;
    }
    if (gLimits.second != 0) {
        return;
    }
    spawn(self);
}
'''


def children(source):
    return [child for _, child in zeroed.variants(source, 'f')]


def test_the_term_of_an_and_chain_compares_with_the_cleared_byte_read_unsigned():
    got = children(CHAINED)
    want = CHAINED.replace('(M2C_FIELD(&gLimits, u8 *, 1) == 0)',
                           '((u8) M2C_FIELD(arg0, u8 *, 0x11) >= M2C_FIELD(&gLimits, u8 *, 1))')
    # the counter no term orders yet comes first
    assert got[0] == want
    assert len(got) == 2


def test_an_early_return_guard_takes_the_other_polarity():
    got = children(GUARDS)
    assert got[0] == GUARDS.replace('if (gLimits.second != 0)', 'if (self->made < gLimits.second)')


def test_it_is_offered_only_where_a_cleared_value_is_ordered_against_a_limit():
    source = CHAINED.replace('>= (u8) M2C_FIELD(&gLimits, u8 *, 0)', '!= 5')
    assert children(source) == []


def test_a_signed_limit_could_be_negative_and_is_left():
    assert children(CHAINED.replace('&gLimits, u8 *, 1', '&gLimits, s8 *, 1')) == []
    assert children(GUARDS.replace('u8 second;', 's8 second;')) == []


def test_a_call_in_between_could_change_the_counter():
    assert children(CHAINED.replace('&& (M2C_FIELD(&gLimits, u8 *, 1) == 0)',
                                    '&& reset(arg0) && (M2C_FIELD(&gLimits, u8 *, 1) == 0)')) == []
    assert children(GUARDS.replace('    self->made = 0;\n', '    self->made = 0;\n    reset(self);\n')) == []


def test_it_declares_itself():
    assert zeroed.REPAIR['families'] == ('zeroed_field_compare',)
    assert any(entry.module.endswith('zeroed_field_compare') for entry in registry.declared())
