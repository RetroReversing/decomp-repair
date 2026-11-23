"""A loop's next value read into a temporary only copied into the loop variable on the continuing arm."""
from decomprepair.loop_carried_temp_copy import FAMILY, variants

# A character copier (KMC GCC 2.7.2): `c` carries the character, `t` is m2c's temporary for the next one.
SAVED = '''inline static s8 __repair_inline(s8 a) { return a; }
void f(u8 *src, s8 *dst) {
    s8 c;
    s8 t;
    s32 n;
    n = 0;
    c = *src;
    for (;;) {
        *dst = c;
        t = __repair_inline(*src);
        dst += 1;
        n += 1;
        if (t == 0) {
        } else {
            c = t;
            continue;
        }
        break;
    }
    Q(n);
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_variable_is_read_directly_and_the_temporary_is_gone():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert any('c = *src; dst += 1; n += 1; if (c != 0) { continue; } break;' in s and ' t =' not in s for s in out)


def test_the_identity_helper_is_kept_in_one_child():
    out = [_squash(src) for _, src in variants(SAVED, 'f')]
    assert any('c = __repair_inline(*src);' in s for s in out)


def test_a_variable_read_after_the_loop_is_left_alone():
    assert variants(SAVED.replace('Q(n);', 'Q(c);'), 'f') == []


def test_a_temporary_used_elsewhere_is_left_alone():
    assert variants(SAVED.replace('Q(n);', 'Q(t);'), 'f') == []


def test_a_statement_between_that_reads_the_variable_is_left_alone():
    assert variants(SAVED.replace('n += 1;', 'n += c;'), 'f') == []
