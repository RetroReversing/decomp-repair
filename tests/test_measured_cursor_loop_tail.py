from decomprepair.measured_cursor_loop_tail import variants

SOURCE = """void insert(Node *node) {
    Node *cursor;
    Node *next;
    cursor = head;
    if (cursor != NULL) {
        for (;;) {
            next = cursor->right;
            if (next == NULL) {
                cursor->right = node;
                break;
            }
            if (((cursor < node) & (node < next)) != 1) {
                cursor = next;
                continue;
            }
            cursor->right = node;
            next->left = node;
            break;
        }
    }
}
"""

ROWS = [
    (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1'),
    ('i', 'beql $v0, $zero, 0xc4', 'beql $v0, $a3, 0x120'),
    (' ', 'move $a0, $a1', 'move $a0, $a1'),
]


def test_cursor_loop_preserves_the_ordered_insert_and_guard():
    [(family, candidate)] = variants(SOURCE, 'insert', ROWS)
    assert family == 'measured_cursor_loop_tail'
    assert 'if (cursor != NULL) {\n        do {' in candidate
    assert 'if ((u8)((cursor < node) & (node < next)) == 0)' in candidate
    assert '''            } else {
                cursor->right = node;
                next->left = node;
                break;
            }
        } while (cursor != NULL);''' in candidate


def test_cursor_loop_requires_nonnull_successor_and_target_edge():
    assert not variants(SOURCE, 'insert', ROWS[:2])
    assert not variants(SOURCE.replace('next == NULL', 'next != NULL'), 'insert', ROWS)
    assert not variants(SOURCE.replace('                break;', '                if (node) break;', 1), 'insert', ROWS)
    assert not variants(SOURCE.replace('Node *cursor;', 'Node *volatile cursor;'), 'insert', ROWS)
