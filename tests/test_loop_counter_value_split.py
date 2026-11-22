"""A loop counter reused after the loop for a fresh value: split, weight, sink (a KMC gcc 2.7.2 table initialiser)."""
from decomprepair import loop_counter_value_split as m

SOURCE = '''extern u8 n; extern char t[]; extern u8 a[];
void f(void) {
 u8 frame[1]; u32 p,q,i;
 for (i = 0; i < n; i++) {
   a[i] = i - 1;
 }
 i=n;
 g=0;
 h=i-1;
 i &= 0xFF; p=0;
 if(i!=0){do{*(u16 *)(t+p)=0;p+=4;}while((s32)p<(u32)(i*4));}
 q=0; do {a[q]=0xFF;q+=1;}while(q<0x100U);
}
'''


def children():
    return [text for family, text in m.variants(SOURCE, 'f')]


def test_the_chain_is_one_child_with_all_three_edits():
    chain = children()[-1]
    assert 'u32 i_loop;' in chain and 'for (i_loop = 0; i_loop < n; i_loop++)' in chain
    assert 'a[i_loop] = i_loop - 1;' in chain
    assert 'do{do{i=n;' in chain and 'i &= 0xFF;}while(0);}while(0);' in chain
    assert 'if(i!=0){\n      p=0;do{' in chain


def test_each_edit_is_offered_alone_too():
    texts = children()
    assert len(texts) == 3
    assert 'do{do{' not in texts[0] and 'i_loop' in texts[0]
    assert 'do{do{' in texts[1] and 'p=0;\n if(i!=0)' in texts[1]


def test_nothing_when_the_counter_is_not_reused():
    assert m.variants(SOURCE.replace('i=n;', 'i=i+n;'), 'f') == []
    assert m.variants(SOURCE.replace('for (i = 0;', 'while (0) {} for (j = 0;'), 'f') == []
