from decomprepair.measured_list_head_insert import variants

SOURCE = '''extern void *head;
typedef struct { void * field_0; int field_4; short field_8; } Rec;
void add(void *node, s32 word, s16 half) {
    s32 saved;
    saved = lock(1);
    ((Rec*)node)->field_4 = word;
    ((Rec*)node)->field_8 = half;
    head = node;
    ((Rec*)node)->field_0 = (void *) head;
    lock(saved, &head);
}
'''
TARGET = ['lui $a1, %hi(head)', 'addiu $a1, $a1, %lo(head)', 'sw $s1, 4($s0)',
          'lw $v1, ($a1)', 'move $a0, $v0', 'sh $s2, 8($s0)', 'sw $v1, ($s0)',
          'jal lock', 'sw $s0, ($a1)']
CANDIDATE = ['sw $s0, %lo(head)($at)', 'sw $s0, ($s0)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(25)]


def test_recovers_previous_head_before_publish():
    result = variants(SOURCE, 'add', '', ROWS)
    assert len(result) == 1
    code = result[0][1]
    assert code.index('field_0 = (void *) *__repair_head;') < code.index('*__repair_head = node;')
    assert '__repair_head = &head;' in code


def test_requires_target_and_source_shape():
    assert not variants(SOURCE, 'add', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('head = node;', 'head = other;'), 'add', '', ROWS)
    assert not variants(SOURCE.replace('extern void *head', 'extern volatile void *head'), 'add', '', ROWS)
    assert not variants(SOURCE.replace('head = node;', '/* note */ head = node;'), 'add', '', ROWS)
