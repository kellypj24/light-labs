// radar-messages-export: the only Relationship Radar code that holds Full Disk Access.
//
// Contract (review this file before granting FDA; README "Reviewing the helper"):
// - No arguments, no config files, no environment variables. Paths come from the
//   password database (getpwuid), not $HOME.
// - Opens ~/Library/Messages/chat.db read-only and runs two fixed queries. No input
//   reaches SQL.
// - Writes metadata only (handle, time, direction, chat members, service) to
//   ~/.relationship-radar/inbox/messages.jsonl, mode 0600, via a temp file and rename.
//   Message text is compiled in only with -D RADAR_SNIPPETS, truncated to 140 characters.
// - Refuses to write unless ~/.relationship-radar and its inbox are both real
//   directories (not symlinks), owned by the user, and not writable by group or others;
//   the file is then created relative to the checked inbox (openat, O_NOFOLLOW).
// - Built with the hardened runtime, which blocks injected libraries (DYLD_*).
//
// The test build (-D RADAR_TEST) takes <chat.db> <radar home> as arguments; it never gets
// FDA. `lab radar helper build` compiles only the copy PJ approved (`helper approve`).

import Foundation
import SQLite3

let maxSnippet = 140

func fail(_ message: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data("radar-messages-export: \(message)\n".utf8))
    exit(code)
}

func homeDirectory() -> String {
    guard let pw = getpwuid(getuid()), let dir = pw.pointee.pw_dir else {
        fail("no home directory for uid \(getuid())")
    }
    return String(cString: dir)
}

#if RADAR_TEST
    guard CommandLine.arguments.count == 3 else { fail("test build: <chat.db> <radar home>", 64) }
    let dbPath = CommandLine.arguments[1]
    let radarHome = CommandLine.arguments[2]
#else
    let home = homeDirectory()
    let dbPath = home + "/Library/Messages/chat.db"
    let radarHome = home + "/.relationship-radar"
#endif

// MARK: - Output directory checks

/// Open `name` inside `parent` as a directory without following a symlink, and require
/// that it is ours and not writable by anyone else. Every directory on the way from
/// the home directory to the inbox goes through this.
func openPrivateDir(_ parent: Int32, _ name: String) -> Int32 {
    let fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
    if fd < 0 { fail("\(name) is missing or a symlink; run `lab radar doctor`") }
    var st = stat()
    guard fstat(fd, &st) == 0 else { fail("cannot stat \(name)") }
    guard st.st_uid == getuid() else { fail("\(name) is not owned by you") }
    guard st.st_mode & (S_IWGRP | S_IWOTH) == 0 else {
        fail("\(name) is writable by group or others")
    }
    return fd
}

let base = (radarHome as NSString).deletingLastPathComponent
let baseFD = open(base, O_RDONLY | O_DIRECTORY)
guard baseFD >= 0 else { fail("cannot open \(base)") }
let radarFD = openPrivateDir(baseFD, (radarHome as NSString).lastPathComponent)
let dirFD = openPrivateDir(radarFD, "inbox")
let inboxPath = radarHome + "/inbox"

// MARK: - Read chat.db

var db: OpaquePointer?
if sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
    fail("cannot open chat.db: \(String(cString: sqlite3_errmsg(db))). "
        + "Grant Full Disk Access to this binary; see `lab radar doctor`.", 77)
}
func query(_ sql: String, _ row: (OpaquePointer) -> Void) {
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let s = stmt else {
        let msg = String(cString: sqlite3_errmsg(db))
        let code: Int32 = msg.contains("authoriz") || msg.contains("unable to open") ? 77 : 1
        fail("query failed: \(msg)", code)
    }
    defer { sqlite3_finalize(s) }
    while true {
        let rc = sqlite3_step(s)
        if rc == SQLITE_ROW { row(s) } else if rc == SQLITE_DONE { break } else {
            fail("step failed: \(String(cString: sqlite3_errmsg(db)))")
        }
    }
}

func text(_ s: OpaquePointer, _ i: Int32) -> String? {
    guard let c = sqlite3_column_text(s, i) else { return nil }
    return String(cString: c)
}

struct ChatRecord: Encodable {
    let type = "chat"
    let chat: String
    let members: [String]
}

struct MessageRecord: Encodable {
    let type = "message"
    let rowid: Int64
    let guid: String
    let from_me: Bool
    let date: Int64
    let sender: String?
    let chat: String
    let service: String?
    let text: String?
}

var members: [String: [String]] = [:]
query(
    """
    SELECT c.guid, h.id
    FROM chat c
    JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
    JOIN handle h ON h.ROWID = chj.handle_id
    ORDER BY c.guid, h.id
    """
) { s in
    if let chat = text(s, 0), let handle = text(s, 1) { members[chat, default: []].append(handle) }
}

var lines = Data()
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]

func emit<T: Encodable>(_ record: T) {
    guard let data = try? encoder.encode(record) else { fail("encode failed") }
    lines.append(data)
    lines.append(0x0A)
}

for (chat, handles) in members.sorted(by: { $0.key < $1.key }) {
    emit(ChatRecord(chat: chat, members: handles))
}

// Regular messages only: no tapbacks or edits (associated_message_type), no
// group-membership events (item_type).
query(
    """
    SELECT m.ROWID, m.guid, m.is_from_me, m.date, h.id, c.guid, m.service, m.text
    FROM message m
    JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    JOIN chat c ON c.ROWID = cmj.chat_id
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    WHERE m.associated_message_type = 0 AND m.item_type = 0
    ORDER BY m.ROWID
    """
) { s in
    guard let guid = text(s, 1), let chat = text(s, 5) else { return }
    var snippet: String? = nil
    #if RADAR_SNIPPETS
        snippet = text(s, 7).map { String($0.prefix(maxSnippet)) }
    #endif
    emit(
        MessageRecord(
            rowid: sqlite3_column_int64(s, 0),
            guid: guid,
            from_me: sqlite3_column_int(s, 2) != 0,
            date: sqlite3_column_int64(s, 3),
            sender: text(s, 4),
            chat: chat,
            service: text(s, 6),
            text: snippet
        ))
}

sqlite3_close(db)

// MARK: - Write: temp file, then atomic rename, all relative to the checked directory

let tmpName = "messages.jsonl.tmp"
let fd = openat(dirFD, tmpName, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0o600)
guard fd >= 0 else { fail("cannot create \(inboxPath)/\(tmpName)") }
let written = lines.withUnsafeBytes { buf -> Int in
    var off = 0
    while off < buf.count {
        let n = write(fd, buf.baseAddress! + off, buf.count - off)
        if n <= 0 { return -1 }
        off += n
    }
    return off
}
guard written == lines.count, fsync(fd) == 0, close(fd) == 0 else { fail("write failed") }
guard renameat(dirFD, tmpName, dirFD, "messages.jsonl") == 0 else { fail("rename failed") }
close(dirFD)
close(radarFD)
close(baseFD)
print("radar-messages-export: wrote \(lines.count) bytes, \(members.count) chats")
