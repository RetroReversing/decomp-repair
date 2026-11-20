from decomprepair import loop_edge_repairs as edges
from decomprepair import operand_lifetime_repairs as operand
from decomprepair import packed_layout_repairs as packed


def test_float_argument_staging_preserves_argument_positions_and_rejects_dependencies():
    source = 'void call(float,float); void f(float x,float y) { call(x-y,x+y); }'
    options = operand.float_argument_order(source,'f','',{('call',(0,1))})
    assert len(options)==2
    assert all('call( repair_arg_0, repair_arg_1)' in text for _,text in options)
    assert 'float repair_arg_0 = x-y; float repair_arg_1' in options[0][1]
    assert 'float repair_arg_1 = x+y; float repair_arg_0' in options[1][1]
    assert not operand.float_argument_order(source.replace('x-y','get()-y'),'f','',{('call',(0,1))})
    ordered = 'void f(float x,float y) { float a,b; a=x-y; b=a+y; call(a,b); }'
    assert not operand.float_argument_order(ordered,'f','',{('call',(0,1))})


def test_divide_square_keeps_precision_and_requires_dead_numerator():
    source = 'void f(void) { float n,d,q; n=read(); d=read(); q=n/d; use(q*q); }'
    [(_, changed)] = operand.divide_square(source,'f','',{'s'})
    assert 'n /= d; n *= n; use(n);' in changed
    assert not operand.divide_square(source,'f','',{'d'})
    assert not operand.divide_square(source.replace('use(q*q)','use(q*q,n)'),'f','',{'s'})
    assert not operand.divide_square(source.replace('use(q*q)','use(flag ? q*q : 0)'),'f','',{'s'})


def test_fresh_offset_leaves_the_search_alone_and_requires_final_use():
    source = ('void f(int i) { int off, n; off=0; n=find(off); off=i*12; '
              '*(u16 *)((u8 *)&a+off)=n; *(u16 *)((u8 *)&b+off)=n; *(u16 *)((u8 *)&c+off)=1; }')
    [(_, candidate)] = operand.final_offset(source,'f','',{12})
    assert 'off=0; n=find(off);' in candidate and 'int repair_insert_offset=i*12;' in candidate
    assert not operand.final_offset(source.replace('=1; }','=1; use(off); }'),'f','',{12})
    assert not operand.final_offset(source,'f','',{16})


def test_retry_supports_comma_declarations_and_rejects_another_incoming_edge():
    source = ('void f(int count,int bound) { int n,off; n=0; retry: off=0; count=0; '
              'do { probe(off); count++; off+=18; } while (count<2); if(count!=bound) goto retry; finish(n); }')
    [(_, candidate)] = edges.reset_retry_counter(source,'f','',{18})
    assert 'count = 0; retry: off=0;' in candidate and '{ count = 0; goto retry; }' in candidate
    assert not edges.reset_retry_counter(source.replace('n=0;','if(n) goto retry;'),'f','',{18})
    assert not edges.reset_retry_counter(source.replace('probe(off)','probe(&(off))'),'f','',{18})


def test_drop_volatile_only_on_the_repeated_ordinary_member_read():
    source = ('typedef struct { u8 limit; } State; void f(void *p) { '
              'u8 n=*(volatile u8 *)&((State*)p)->limit; '
              'for (;;) { if(n) break; n=*(volatile u8 *)&((State*)p)->limit; } }')
    [(_, candidate)] = edges.ordinary_backedge_read(source,'f','')
    assert candidate.count('volatile u8')==1 and 'n=*(u8 *)&((State*)p)->limit;' in candidate
    assert not edges.ordinary_backedge_read(source.replace('{ u8 limit;','{ volatile u8 limit;'),'f','')
    assert not edges.ordinary_backedge_read(source.replace('n=*(volatile u8 *)&((State*)p)->limit; }','n=*(volatile u8 *)0x1000; }'),'f','')


def test_wide_clear_requires_a_single_typed_word_pair():
    source = 'extern u64 data; void f(void) { ((u32 *)&data)[0]=0; ((u32 *)&data)[1]=0; }'
    assert packed.aligned_clear(source,'f','',{'data'}) == [(packed.WIDE_CLEAR,'extern u64 data; void f(void) { data = 0; }')]
    assert not packed.aligned_clear(source.replace('u64 data','u32 data[2]'),'f','',{'data'})
    assert not packed.aligned_clear(source.replace('[1]','[0]'),'f','',{'data'})
