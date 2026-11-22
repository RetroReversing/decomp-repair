from decomprepair import field_cursor_index as r

TYPED = '''typedef struct Node {
    s32 a;
    struct Node *next;
    f32 cost;
    struct Node *nbr[16];
} Node;
extern s32 total;
void visit(Node *);

void f(Node *cur) {
    u32 i;
    i = 0;
    {
        char *q = (char *) cur;
        do {
            Node *nb = ((volatile Node *) q)->nbr[0];
            i++;
            if (nb != NULL && nb->cost == -1.0f) {
                if (total) {
                    visit(((volatile Node *) q)->nbr[0]);
                } else {
                    visit(((volatile Node *) q)->nbr[0]);
                }
            }
            q += sizeof(Node *);
        } while (i < 16);
    }
}
'''

M2C = '''extern void *D;
void visit(void *);

void f(void *var_s1) {
    u32 var_s2;
    void *var_s0;
    void *temp;

    var_s2 = 0;
    var_s0 = var_s1;
    do {
        temp = M2C_FIELD(var_s0, void **, 0x14);
        var_s2 += 1;
        if (temp != NULL) {
            visit(M2C_FIELD(var_s0, void **, 0x14));
        }
        var_s0 += 4;
    } while (var_s2 < 0x10U);
}
'''


def only(source, family='field_cursor_index'):
    out = [text for fam, text in r.variants(source, 'f') if fam == family]
    assert len(out) == 1
    return out[0]


def test_a_byte_cursor_over_a_member_array_becomes_the_indexed_for_loop():
    text = only(TYPED)
    assert 'for (i = 0; i < 16; i++) {' in text
    assert 'Node *nb = cur->nbr[i];' in text and 'visit(cur->nbr[i]);' in text
    assert 'char *q' not in text and 'volatile' not in text and 'i++;' not in text.split('for (')[1].split('\n', 1)[1]
    assert 'do {' not in text and 'while (i < 16)' not in text


def test_the_scaffolding_stripped_child_is_the_combination():
    text = only(TYPED, 'field_cursor_index_strip')
    assert 'for (i = 0; i < 16; i++) {' in text and 'if (total)' not in text
    assert text.count('visit(cur->nbr[i]);') == 1


def test_an_m2c_field_cursor_reads_the_offset_plus_the_counter_multiple():
    text = only(M2C)
    assert 'for (var_s2 = 0; var_s2 < 0x10U; var_s2++) {' in text
    assert 'temp = M2C_FIELD(var_s1, void **, 0x14 + var_s2 * 4);' in text
    assert 'visit(M2C_FIELD(var_s1, void **, 0x14 + var_s2 * 4));' in text
    assert 'var_s0' not in text and 'var_s2 += 1' not in text


def test_a_step_that_is_not_the_element_size_is_left_alone():
    assert r.variants(TYPED.replace('q += sizeof(Node *);', 'q += 8;'), 'f') == []


def test_a_bound_beyond_the_array_is_left_alone():
    assert r.variants(TYPED.replace('i < 16', 'i < 17'), 'f') == []


def test_a_counter_that_does_not_start_at_zero_is_left_alone():
    assert r.variants(TYPED.replace('i = 0;', 'i = 1;'), 'f') == []
    assert r.variants(TYPED.replace('    i = 0;\n', '    i = 0;\n    if (total) { i = 2; }\n'), 'f') == []


def test_a_counter_read_in_the_body_is_left_alone():
    assert r.variants(TYPED.replace('visit(((volatile Node *) q)->nbr[0]);\n                } else',
                                    'visit(((volatile Node *) q)->nbr[0]); total = i;\n                } else'), 'f') == []


def test_a_cursor_used_any_other_way_is_left_alone():
    assert r.variants(TYPED.replace('if (total) {', 'if (q) {'), 'f') == []


def test_a_cursor_read_after_the_loop_is_left_alone():
    assert r.variants(TYPED.replace('    }\n}\n', '    }\n    total = (s32) q;\n}\n'), 'f') == []


def test_a_base_the_loop_assigns_is_left_alone():
    assert r.variants(TYPED.replace('i++;\n', 'i++;\n            cur = nb;\n'), 'f') == []


def test_a_loop_that_can_leave_early_is_left_alone():
    assert r.variants(TYPED.replace('visit(((volatile Node *) q)->nbr[0]);\n                } else',
                                    'break;\n                } else'), 'f') == []
