from decomprepair.measured_layout_repairs import paired_word_copy, unused_frame_array
from decomprepair.symbols import Symbol, SymbolTable

DEST,FIRST,SECOND = 'D_80008000','D_80009000','D_80009004'

TARGET = [
    f'lui $v0, %hi({DEST})',f'addiu $v0, $v0, %lo({DEST})',
    f'lui $v1, %hi({FIRST})',f'lw $v1, %lo({FIRST})($v1)',
    f'lui $a0, %hi({SECOND})',f'lw $a0, %lo({SECOND})($a0)',
    'sw $v1, ($v0)','sw $a0, 4($v0)',
]
ROWS = [(' ',text,text) for text in TARGET[:6]]+[('<',text,'') for text in TARGET[6:]]
SYMBOLS = SymbolTable([Symbol(DEST,0x80008000,8), Symbol(FIRST,0x80009000,4), Symbol(SECOND,0x80009004,4)])
HEADER = f'extern s32 {FIRST}, {SECOND};'
FIELDS = f'void f(void) {{ M2C_FIELD(&{DEST},s32 *,0)={FIRST}; M2C_FIELD(&{DEST},s32 *,4)={SECOND}; }}'
POINTER = f'void f(void) {{ {{ s32 *p=(s32 *)&{DEST}; p[0]={FIRST}; p[1]={SECOND}; }} }}'


def test_paired_copy_needs_a_shared_base_and_adjacent_source_words():
    for source in (FIELDS,POINTER):
        [(family,candidate)] = paired_word_copy(source,'f',HEADER,ROWS,SYMBOLS)
        assert family=='measured_paired_word_copy'
        assert f'*(__repair_word_pair *)&{DEST} = *(__repair_word_pair *)&{FIRST};' in candidate
        assert not paired_word_copy(source,'f',HEADER,ROWS,SYMBOLS,('-fstrict-aliasing',))
        assert not paired_word_copy(source,'f',HEADER,ROWS[:7]+[('<','sw $a0, 4($a2)','')],SYMBOLS)
        assert not paired_word_copy(source,'f',HEADER,ROWS,SymbolTable())
    assert not paired_word_copy(FIELDS,'f',HEADER.replace('s32','volatile s32'),ROWS,SYMBOLS)


def test_excess_frame_removes_only_an_unused_outer_array_of_matching_size():
    source = 'int f(void) { char frame[8]; return 1; }'
    report = dict(frame_delta=-8,saved_deltas=[-8],local_deltas=[])
    rows = [('s','addiu $sp, $sp, -0x18','addiu $sp, $sp, -0x20')]
    assert unused_frame_array(source,'f',rows,report) == [
        ('measured_unused_frame_array','int f(void) {  return 1; }'),
    ]
    assert not unused_frame_array(source.replace('return 1','return frame[0]'),'f',rows,report)
    assert not unused_frame_array(source.replace('[8]','[16]'),'f',rows,report)
    assert not unused_frame_array(source,'f',rows,dict(report,local_deltas=[-8]))
    assert not unused_frame_array(source,'f',rows+[('r','nop','move $v0, $a0')],report)
