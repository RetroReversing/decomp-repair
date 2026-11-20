from decomprepair import target_memory_schedule_repairs as repairs


def apply(source,method,witness):
    return [code for _,code in repairs.variants(source,'f','',[(method,witness)])]


def test_middle_reload_keeps_three_volatile_pointer_reads():
    source = ('extern void *volatile current; void f(void) { void *p; p=current; use(p); p=current; '
              '*(int *)((unsigned char *)p+8)|=32; p=current; use(p); }')
    [new] = apply(source,repairs.middle_reload,{('current',8)})
    assert 'int *repair_flags = (int *)((unsigned char *)current + 8)' in new
    assert new.count('p=current;')==2
    assert not apply(source.replace('volatile ',''),repairs.middle_reload,{('current',8)})
    assert not apply(source,repairs.middle_reload,{('current',12)})


def test_ido_chain_keeps_the_word_and_both_offsets():
    source = 'void f(unsigned char *p) { *(short *)(p+8)=*(int *)(p+4)=*(short *)(p+2)=0; }'
    [new] = apply(source,repairs.zero_chain,{(2,4,8)})
    assert '*(unsigned short *)(p+8)=*(int *)(p+4)=*(unsigned short *)(p+2)=0;' in new
    assert not apply(source,repairs.zero_chain,{(2,8,4)})


def test_stack_mask_uses_only_a_proven_in_bounds_array_word():
    source = 'void f(void) { unsigned int a[4]; init(a); use((a[0]&0xffffff)); }'
    [new] = apply(source,repairs.stack_mask,{0xffffff})
    assert 'repair_masked_word = a[0]; repair_masked_word &= 0xffffff;' in new
    assert not apply(source.replace('a[0]','a[4]'),repairs.stack_mask,{0xffffff})


def test_extract_self_contained_volatile_loop_with_ordered_invariants():
    source = ('extern unsigned char base; void f(void) { volatile unsigned char *p=&base; '
              'int i=4; int step=2; int end=32; for (;i<end;i+=step) { p[i]=0; } }')
    [new] = apply(source,repairs.inline_invariants,{(4,2,32,None)})
    assert 'static inline void repair_ordered_loop(int i, int step, int end, volatile unsigned char * p)' in new
    assert 'repair_ordered_loop(4, 2, 32, &base);' in new
    assert not apply(source.replace('p[i]=0','p[i]=unknown'),repairs.inline_invariants,{(4,2,32,None)})
