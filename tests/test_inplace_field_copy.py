"""A field read of a packed word that the run later overwrites in place, moved after the overwrite through a copy."""
from decomprepair.inplace_field_copy import FAMILY, variants

# A triangle command's three 5-bit vertex indices from one 16-bit word (SN64 GCC 2.8.1): the word's variable becomes
# the last field in place.
DECODE = '''void f(u8 *cmd, u32 *out)
{
    s32 b;
    s32 r;
    s32 k;
    b = cmd[2] + (cmd[1] << 8);
    r = b & 0x1F;
    k = ((u32)b >> 5) & 0x1F;
    b = (b >> 10) & 0x1F;
    out[0] = (k << 9) | (b << 1) | r;
}
'''

WANT = '''    {
        s32 b_1 = b;
        k = ((u32)b >> 5) & 0x1F;
        b = (b >> 10) & 0x1F;
        r = b_1 & 0x1F;
    }
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_first_field_is_read_through_a_copy_after_the_overwrite():
    kids = _children(DECODE)
    assert any(WANT in k and '    r = b & 0x1F;' not in k for k in kids)


def test_a_read_of_something_the_run_writes_in_between_stays():
    text = DECODE.replace('    r = b & 0x1F;', '    r = (b + k) & 0x1F;')
    assert not any('r = (b_1 + k)' in k for k in _children(text))


def test_a_target_read_in_between_stays():
    text = DECODE.replace('    k = ((u32)b >> 5) & 0x1F;', '    k = ((u32)b >> 5) & r;')
    assert not any('r = b_1 & 0x1F' in k for k in _children(text))


def test_no_in_place_update_no_children():
    assert _children(DECODE.replace('    b = (b >> 10) & 0x1F;', '    r = (b >> 10) & 0x1F;')) == []


def test_volatile_and_address_taken_decline():
    assert _children(DECODE.replace('    s32 r;', '    volatile s32 r;')) == []
    assert _children(DECODE.replace('    out[0] =', '    g(&b);\n    out[0] =')) == []
