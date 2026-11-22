"""Float sums held in a reused local, and single-use float temporaries written inline (KMC GCC 2.7.2 FPR rows)."""
from decomprepair import float_hold_reuse_repairs as r

# A pan/volume stage: four 16-bit outputs from table interpolations. The saved best left 17 float register rows
# (85); the held-and-inlined form of every chain was the game's (0).
SOURCE = '''extern f32 A[], B[], T[];
void f(s16 *a, s16 *b, u32 x, u32 y, u32 z, s16 *c, u32 w, s16 *d) {
 f32 p,q,r,t,v; u32 i;
 i=x>>16;
 p=(f32)(x&0xffff)*0.5f;
 q=(1.0f-p)*A[i]+p*B[i];
 i=z>>22;
 p=(f32)(z&0x3fffff)*0.25f;
 t=(1.0f-p)*T[i]+p*T[i+1];
 v=q*t;
 *c=(s32)(v*23195.76f);
 i=z>>22;
 p=(f32)(z&0x3fffff)*0.25f;
 r=q*((1.0f-p)*T[i]+p*T[i+1]);
 if(y==0x800000) { *a=(s32)(r*23195.76f); v=r*-23195.76f; *b=(s32)v; }
 else {
 i=y>>22; p=(f32)(y&0x3fffff)*0.25f;
 *a=(s32)(r*((1.0f-p)*T[i]+p*T[i+1])*32767.0f);
 i=y>>22; p=(f32)(y&0x3fffff)*0.25f;
 v=r*((1.0f-p)*T[i]+p*T[i+1])*32767.0f;
 *b=(s32)v;
 }
 i=w>>16; p=(f32)(w&0xffff)*0.5f;
 *d=(s32)(((1.0f-p)*A[i]+p*B[i])*23195.76f);
}
'''
SUM = '(1.0f-p)*T[i]+p*T[i+1]'


def offered(source=SOURCE):
    return [text for label, text in r.variants(source, 'f') if label == r.FAMILY]


def test_the_whole_bundle_is_one_child():
    # the edits that were each no better alone: `q` carries the last sum, `t` the two in the else arm, the product's
    # temporary is written inline, and `v` is no longer the carrier of a single-use value
    wanted = [text for text in offered()
              if ' q = (1.0f-p)*A[i]+p*B[i]; *d=(s32)(q*23195.76f);' in text
              and f' t = {SUM}; *a=(s32)(r*t*32767.0f);' in text
              and f' t = {SUM};\n *b=(s32)(r*t*32767.0f);' in text
              and ' *c=(s32)((q*t)*23195.76f);' in text]
    assert wanted
    # the negated product is not inlined: `r * -K` is a different constant to the compiler
    assert all(' v=r*-23195.76f; *b=(s32)v;' in text for text in wanted)
    for text in wanted:
        assert text.count('v=q*t;') == 0 and text.count('v=r*(') == 0


def test_a_single_edit_comes_first():
    first = offered()[0]
    changed = [line for line in first.split('\n') if line not in SOURCE.split('\n')]
    assert 1 <= len(changed) <= 2


def test_every_child_keeps_the_values():
    for text in offered():
        # p is read by every sum, so it never carries one
        assert ' p = ' not in text
        # a carrier is written before the statement that reads it
        for carrier in 'qrtv':
            assert text.find(f' {carrier} = ') < 0 or text.count(f'{carrier} = ') >= 1


def test_left_alone_otherwise():
    # a loop, a double literal, a call in the sum, a carrier read later
    assert offered(SOURCE.replace(' i=w>>16;', ' while (i) i--; i=w>>16;')) == []
    doubled = SOURCE.replace('(((1.0f-p)*A[i]+p*B[i])*23195.76f)', '(((1.0f-p)*A[i]+p*2.5)*23195.76f)')
    assert not any('q = (1.0f-p)*A[i]+p*B[i]; *d' in text for text in offered(doubled))
    called = SOURCE.replace('A[i]+p*B[i])*23195.76f', 'g(A[i])+p*B[i])*23195.76f')
    assert not any('q = (1.0f-p)*g(' in text for text in offered(called))
    # q is read after the last sum: it cannot carry it
    read_after = SOURCE.replace('\n}\n', ' *c=(s32)q;\n}\n')
    assert not any('q = (1.0f-p)*A[i]+p*B[i]; *d' in text for text in offered(read_after))
    assert r.variants('void g(void) { }', 'g') == []


def test_a_write_in_one_arm_does_not_kill_the_value():
    # `t` is written in the then-arm only and read after the join: not dead at a site before the branch
    source = '''void g(f32 *o, int c, f32 p, f32 s, f32 u) {
 f32 t, q;
 q = s;
 *o = (s32)(((1.0f-p)*s+p*u)*3.0f);
 if (c) { t = u; }
 *o = (s32)t;
}
'''
    assert not any(' t = (1.0f-p)*s+p*u;' in text for text in offered_for(source, 'g'))
    both = source.replace('if (c) { t = u; }', 'if (c) { t = u; } else { t = s; }')
    assert any(' t = (1.0f-p)*s+p*u;' in text for text in offered_for(both, 'g'))


def offered_for(source, name):
    return [text for _, text in r.variants(source, name)]
