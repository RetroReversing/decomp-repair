from decomprepair.measured_expression_repairs import variants


def rows(a,b):
    return [(' ' if x==y else 'r',x,y) for x,y in zip(a.split('|'),b.split('|'),strict=True)]


def test_signed_bit_test_keeps_original_load():
    source = 's32 f(void) { s32 status = *(volatile s32 *)0x8000; return (status & 0x80000000U) != 0; }'
    diff = rows('jr $ra|slti $v0, $v0, 0','jr $ra|srl $v0, $v0, 0x1f')
    assert variants(source,'f','',diff) == [('measured_sign_test',source.replace('& 0x80000000U','>> 31'))]
    assert not variants(source.replace('s32 status','u32 status'),'f','',diff)
    assert not variants(source,'f','',diff[1:])


def test_halfword_member_retains_the_measured_pointer_advance():
    header = 'extern u16 *p; typedef struct { u16 field_0; u8 pad[10]; u16 field_C; } R;'
    source = 'void f(void) { again: p += 6; if (((R*)p)->field_C != 0) goto again; }'
    diff = rows('lhu $v1, 0xc($a1)|addiu $v0, $a1, 12','lhu $v1, 0x18($a1)|addiu $v0, $a1, 12')
    assert variants(source,'f',header,diff) == [('measured_advanced_field',source.replace('field_C','field_0'))]
    assert not variants(source, 'f', header.replace('u16 field_0','u8 field_0'), diff)
    assert not variants(source.replace('+= 6','+= 7'),'f',header,diff)


def test_scaled_expression_needs_a_bounded_input_and_a_matching_register_chain():
    source = ('void f(u16 x) { s32 n; n = x & 0xFFFF; if (n) { s32 scaled = n * 5; '
              's32 base = M2C_FIELD(obj, s32 *, 0xC); scaled = (scaled << 2) - 0x14; save(base+scaled); } }')
    target = 'sll $v0, $v1, 2|addu $v0, $v0, $v1|lw $v1, 0xc($a3)|sll $v0, $v0, 2|addiu $v0, $v0, -0x14|addu $v1, $v1, $v0'
    prior = 'sll $v0, $v1, 2|addu $v1, $v0, $v1|lw $v0, 0xc($a3)|sll $v1, $v1, 2|addiu $v1, $v1, -0x14|addu $v0, $v0, $v1'
    diff = rows(target,prior)
    expected = source.replace('n * 5','((n << 2) + n) << 2').replace('(scaled << 2)','scaled')
    assert variants(source,'f','',diff) == [('measured_scaled_expression',expected)]
    assert not variants(source.replace('x & 0xFFFF','x'),'f','',diff)
    assert not variants(source,'f','',rows(target.replace('-0x14','-0x15'),prior))


def test_float_conversion_stays_in_the_same_guard():
    source = ('f32 f(f32 x) { f32 value; f32 neg; s32 n; n = read(); '
              'if (n) { neg = -x; if ((value = (f32) (n >> 1)) < neg) value = neg; } return value; }')
    diff = rows('|mtc1 $v0, $f2|nop|cvt.s.w $f2, $f2|neg.s $f0, $f4|c.lt.s $f2, $f0',
                'neg.s $f0, $f4|mtc1 $v0, $f2|nop|cvt.s.w $f2, $f2||c.lt.s $f2, $f0')
    [(family,candidate)] = variants(source,'f','',diff)
    assert family=='measured_staged_negation'
    assert 'if (n) { do { value = (f32) (n >> 1); } while (0);' in candidate
    assert 'if (value < neg)' in candidate
    assert not variants(source.replace('f32 neg','volatile f32 neg'),'f','',diff)
    assert not variants(source,'f','',diff[:-1])
