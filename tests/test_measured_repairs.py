from decomprepair import measured_arithmetic_repairs as arithmetic
from decomprepair import measured_control_repairs as control
from decomprepair import measured_storage_repairs as storage


def test_selector_requires_later_use_and_cannot_cross_an_escape_or_conditional():
    source = 'int f(int x) { int m = 0; state->x = x; x = helper(x); return m + x; }'
    [(_, candidate)] = control.selector_after_call(source,'f','',{('helper',0)})
    assert 'int m; state->x = x; x = helper(x); m = 0;' in candidate
    assert not control.selector_after_call(source.replace('state->x = x;', 'expose(&m);'),'f','',{('helper',0)})
    assert not control.selector_after_call(source.replace('x = helper(x);','if (x) x = helper(x);'),'f','',{('helper',0)})
    assert not control.selector_after_call(source.replace('helper(x)','helper(x+m)'),'f','',{('helper',0)})


def test_field_first_reorders_only_a_plain_compare_after_a_dominating_entry():
    source = ('void f(char *p,char *other) { if (p!=0) do { '
              'if ((p!=other) && (*(short *)((char *)p + 0x78) == 1) && cond(p)) { use(p); } '
              'p = next(p); } while (p!=0); }')
    [(_, candidate)] = control.field_first(source,'f','',{0x78})
    assert 'if ((*(short *)((char *)p + 0x78) == 1)) { if ((p!=other) && cond(p))' in candidate
    assert not control.field_first(source,'f','',{0x44})
    assert not control.field_first(source.replace('if (p!=0) do {','if (p!=0) ordinary(); do {'),'f','',{0x78})
    assert not control.field_first(source.replace('while (p!=0)','while (true)'),'f','',{0x78})


def test_loop_bound_never_moves_across_a_mutated_input_or_continue():
    source = ('void f(int length) { int i; int limit; i=0; if(length>3) { '
              'limit=(int)(unsigned short)length-3; do { update(i); i++; } while (i<limit); } }')
    [(_, candidate)] = control.loop_tail_bound(source,'f','',{-3})
    assert 'do { update(i); i++;  limit=(int)(unsigned short)length-3;' in candidate
    assert not control.loop_tail_bound(source.replace('update(i);','length++;'),'f','',{-3})
    assert not control.loop_tail_bound(source.replace('update(i);','if(i) continue;'),'f','',{-3})
    assert not control.loop_tail_bound(source.replace('update(i);','update(&length);'),'f','',{-3})


def test_delayed_scaled_pointer_follows_a_known_macro_store():
    header = '#define M2C_FIELD(obj, typ, off) (*(typ)(((s8 *)(obj) + (off))))'
    source = ('void f(int i, void *obj) { void **p; char *base; void *x; '
              'base = table; p = (i*4) + base; M2C_FIELD(obj,s8*,0x12) = 0; x = *p; use(x,p); }')
    [(_, candidate)] = storage.delayed_pointer(source,'f',header,{4})
    assert 'M2C_FIELD(obj,s8*,0x12) = 0; x = *((void **)((i*4) + base)); p = (i*4) + base;' in candidate
    assert not storage.delayed_pointer(source,'f',header.replace('*(typ)','fn(typ)'),{4})
    assert not storage.delayed_pointer(source.replace('M2C_FIELD(obj,','M2C_FIELD(p,'),'f',header,{4})


def test_aggregate_preserves_locations_and_does_not_guess_at_overlapping_arrays():
    code = ('void f(void) { float sp20[3]; int sp10[3]; '
            'sp10[0]=1; sp20[0]=2; use(sp10, sp20); }')
    [(_, candidate)] = storage.stack_array_record(code,'f','',{0x10,0x20},{0x10,0x20})
    assert 'int sp10[3]; unsigned char gap_1C[4]; float sp20[3];' in candidate
    assert 'use(repair_stack_record.sp10, repair_stack_record.sp20)' in candidate
    assert not storage.stack_array_record(code.replace('sp10[3]','sp10[5]'),'f','',{0x10,0x20},{0x10,0x20})
    assert not storage.stack_array_record(code,'f','',{0x10,0x24},{0x10,0x20})


def test_strided_fields_require_unchanged_scaled_index():
    code = ('extern char a[]; extern char b[]; int f(int i) { int off; int v; '
            'off=i*12; v=*(u32 *)(a + off); return v+*(u16 *)(b + off); }')
    views = [(12,{'a':4,'b':2})]
    [(_, candidate)] = storage.strided_fields(code,'f','',views)
    assert 'unsigned char padding[10]' in candidate
    assert not storage.strided_fields(code.replace('return v+','++off; return v+'),'f','',views)
    assert not storage.strided_fields(code,'f','',[(20,views[0][1])])


def test_float_reuse_and_halfword_widening_require_dead_unescaped_storage():
    float_code = ('double f(double x) { double earlier=1.0; double scale; if(x>earlier) return x; '
                  'scale=3.0; return calc(x)*scale; }')
    assert arithmetic.reused_float(float_code,'f','')
    assert not arithmetic.reused_float(float_code.replace('calc(x)*scale','calc(x)*scale+earlier'),'f','')
    assert not arithmetic.reused_float(float_code.replace('if(x>earlier)','save(&earlier); if(x>earlier)'),'f','')
    halfword = 'void f(short *p, short *out) { short w; w=*(short *)p; *(short *)out = w & 0xffe0; }'
    assert arithmetic.halfword_use(halfword,'f','',{0xffe0})
    assert not arithmetic.halfword_use(halfword.replace('*(short *)out','save(&w); *(short *)out'),'f','',{0xffe0})
