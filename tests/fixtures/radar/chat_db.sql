-- The subset of chat.db that the helper reads. Synthetic rows only.
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, style INTEGER);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, handle_id INTEGER, service TEXT,
    date INTEGER, is_from_me INTEGER, associated_message_type INTEGER DEFAULT 0,
    item_type INTEGER DEFAULT 0
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);

INSERT INTO handle VALUES (1, '+14155550101', 'iMessage'), (2, 'bob@example.com', 'iMessage'),
    (3, '+14155550104', 'SMS');
INSERT INTO chat VALUES (1, 'iMessage;-;+14155550101', 45), (2, 'iMessage;+;chat123', 43);
INSERT INTO chat_handle_join VALUES (1, 1), (2, 2), (2, 3);
INSERT INTO message VALUES
    (1, 'm1', 'hi there', 1, 'iMessage', 783000000000000000, 0, 0, 0),
    (2, 'm2', 'a reply that is long enough to be truncated at one hundred and forty characters by the helper when it is built with snippets on; padding padding padding', 0, 'iMessage', 783000060000000000, 1, 0, 0),
    (3, 'm3', NULL, 1, 'iMessage', 783000070000000000, 0, 2000, 0),
    (4, 'm4', 'group hello', 2, 'iMessage', 783000080000000000, 0, 0, 0),
    (5, 'm5', NULL, 0, 'iMessage', 783000090000000000, 1, 0, 1),
    (6, 'm6', 'old-style seconds', 3, 'SMS', 500000000, 0, 0, 0);
INSERT INTO chat_message_join VALUES (1, 1, 0), (1, 2, 0), (1, 3, 0), (2, 4, 0), (2, 5, 0), (2, 6, 0);
