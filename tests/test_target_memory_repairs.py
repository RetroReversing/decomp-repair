from decomprepair import target_arithmetic_repairs as arithmetic
from decomprepair import target_memory_repairs as memory


def test_postfix_requires_explicitly_volatile_byte_and_standalone_increment():
    source = 'extern volatile u8 flag; void f(void) { flag += 1; use(); }'
    assert memory.volatile_postfix(source,'f','',{'flag'}) == [
        (memory.POSTFIX,source.replace('flag += 1;','flag++;'))]
    assert not memory.volatile_postfix(source.replace('volatile ',''),'f','',{'flag'})
    assert not memory.volatile_postfix(source.replace('u8','u32'),'f','',{'flag'})
    assert not memory.volatile_postfix(source.replace('flag +=','if (q) flag +='),'f','',{'flag'})
    assert not memory.volatile_postfix(source,'f','#define flag other',{'flag'})


def test_one_arm_offset_rejects_changed_or_address_taken_values():
    source = ('void f(int q) { int i,off; i=0; off=i*12; if (q) { use(*(&left+off)); } '
              'else { use(*(&right+off)); } }')
    [(_, candidate)] = memory.branch_offset(source,'f','',{'right'})
    assert '*(&left+off)' in candidate and '*(&right+((int)(i*12)))' in candidate
    assert not memory.branch_offset(source.replace('if (q)','++i; if (q)'),'f','',{'right'})
    assert not memory.branch_offset(source.replace('if (q)','bind(&i); if (q)'),'f','',{'right'})
    assert not memory.branch_offset(source.replace('if (q)','if (change(q))'),'f','#define change(q) (++i)',{'right'})


def test_global_decrement_preserves_width_and_accepts_comma_declarations():
    source = 'extern s16 x, next; void f(void) { int i = x; do { --i; } while(i>0); i = next - 1; use(i); }'
    [(_, candidate)] = memory.split_decrement(source,'f','',{'next'})
    assert 'i = next; --i; use(i);' in candidate
    assert not memory.split_decrement(source.replace('s16 x, next','u32 x, next'),'f','',{'next'})
    assert not memory.split_decrement(source.replace('s16 x, next','int x, next').replace('next - 1','next - 1U'),
                                      'f','',{'next'})
    assert not memory.split_decrement(source.replace('i = next - 1;','q ? touch() : i = next - 1;'),'f','',{'next'})


def test_exit_reset_cannot_skip_a_live_use_or_an_existing_other_exit():
    source = 'void f(void) { u32 i; unsigned int n; i=0; do { i+=1; work(); } while(i<3U); n=0; call(); }'
    assert arithmetic.exit_reset(source,'f','extern volatile int state;',{3},{'call'})
    assert not arithmetic.exit_reset(source.replace('work();','if(state) break; work();'),'f','',{3},{'call'})
    assert not arithmetic.exit_reset(source.replace('work();','work(n);'),'f','',{3},{'call'})


def test_accumulator_preserves_typed_helper_and_addition_order():
    source = ('extern float root(float); float f(float *p) { float a=p[0]; float b=p[1]; float c=p[2]; '
              'float result=root(a*a+b*b+c*c); return result; }')
    [(_, candidate)] = arithmetic.float_accumulator(source,'f','',{'s'})
    assert 'float result = a*a; result += b*b; result += c*c; result = root(result);' in candidate
    assert not arithmetic.float_accumulator(source.replace('root(float)','root(double)'),'f','',{'s'})
    assert not arithmetic.float_accumulator(source.replace('a*a+b*b+c*c','a*a+(b*b+c*c)'),'f','',{'s'})


def test_timer_uses_the_observed_offset_and_keeps_unsigned_subtraction():
    source = ('#define FIELD(p, T, off) (*(T *)((p) + (off)))\n'
              'void f(char *p,u32 step) { s32 t; t=FIELD(p,s32,0x14); if(t>0) { t=(u32)t-step; '
              'FIELD(p,s32,0x14)=t; if(t<=0) call(); } }')
    [(_, candidate)] = memory.direct_timer(source,'f','',{0x14})
    assert 'FIELD(p,s32,0x14) -= step;' in candidate
    assert not memory.direct_timer(source,'f','',{0x18})
    assert not memory.direct_timer(source.replace('u32 step','int step'),'f','',{0x14})
    assert not memory.direct_timer(source.replace('(*(T *)((p) + (off)))','lookup(p, off)'),'f','',{0x14})
