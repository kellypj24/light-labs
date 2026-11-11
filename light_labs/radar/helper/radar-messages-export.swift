// radar-messages-export: the only Relationship Radar code that holds Full Disk Access.
//
// Contract (review this file before granting FDA; docs/radar.md "Reviewing the helper"):
// - No arguments, no config files, no environment variables. Paths come from the
//   password database (getpwuid), not $HOME.
// - Opens, read-only, ~/Library/Messages/chat.db and the Contacts databases under
//   ~/Library/Application Support/AddressBook (the root one and Sources/*/), and runs
//   fixed queries. No input reaches SQL.
// - Writes metadata only:
//   messages.jsonl: handle, time, direction, chat members, service.
//   contacts.jsonl: names, organization, job title, birthday, phones, emails, and
//   which card is PJ's own ("My Card"). No notes, addresses, photos or relations.
//   Message text is compiled in only with -D RADAR_SNIPPETS: the newest message per
//   chat, direction and sender, truncated to 140 characters (one more fixed query).
// - Both files go to ~/.relationship-radar/inbox, mode 0600, via a temp file and rename.
//   It refuses to write unless ~/.relationship-radar and its inbox are both real
//   directories (not symlinks), owned by the user, and not writable by group or others;
//   files are created relative to the checked inbox (openat, O_NOFOLLOW).
// - Contacts are best effort: if they can't be read, contacts.jsonl holds one error
//   record and the Messages export still runs.
// - Built with the hardened runtime, which blocks injected libraries (DYLD_*).
//
// The test build (-D RADAR_TEST) takes <chat.db> <AddressBook dir> <radar home> as
// arguments; it never gets FDA. `lab radar helper build` compiles only the copy PJ
// approved (`lab radar helper approve`).

import Foundation
import SQLite3

let maxSnippet = 140

func fail(_ message: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data("radar-messages-export: \(message)\n".utf8))
    exit(code)
}

func warn(_ message: String) {
    FileHandle.standardError.write(Data("radar-messages-export: \(message)\n".utf8))
}

func homeDirectory() -> String {
    guard let pw = getpwuid(getuid()), let dir = pw.pointee.pw_dir else {
        fail("no home directory for uid \(getuid())")
    }
    return String(cString: dir)
}

#if RADAR_TEST
    guard CommandLine.arguments.count == 4 else {
        fail("test build: <chat.db> <AddressBook dir> <radar home>", 64)
    }
    let chatPath = CommandLine.arguments[1]
    let addressBookDir = CommandLine.arguments[2]
    let radarHome = CommandLine.arguments[3]
#else
    let home = homeDirectory()
    let chatPath = home + "/Library/Messages/chat.db"
    let addressBookDir = home + "/Library/Application Support/AddressBook"
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

/// Write `data` to inbox/<name> through a temp file and an atomic rename.
func writeInbox(_ name: String, _ data: Data) {
    let tmp = name + ".tmp"
    let fd = openat(dirFD, tmp, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0o600)
    guard fd >= 0 else { fail("cannot create \(inboxPath)/\(tmp)") }
    let written = data.withUnsafeBytes { buf -> Int in
        var off = 0
        while off < buf.count {
            let n = write(fd, buf.baseAddress! + off, buf.count - off)
            if n <= 0 { return -1 }
            off += n
        }
        return off
    }
    guard written == data.count, fsync(fd) == 0, close(fd) == 0 else { fail("write failed") }
    guard renameat(dirFD, tmp, dirFD, name) == 0 else { fail("rename failed") }
}

// MARK: - SQLite, read-only

func openReadOnly(_ path: String) -> (OpaquePointer?, String?) {
    var db: OpaquePointer?
    if sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
        let msg = String(cString: sqlite3_errmsg(db))
        sqlite3_close(db)
        return (nil, msg)
    }
    return (db, nil)
}

/// Run one fixed query; nil on success, the SQLite error otherwise.
func query(_ db: OpaquePointer, _ sql: String, _ row: (OpaquePointer) -> Void) -> String? {
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let s = stmt else {
        return String(cString: sqlite3_errmsg(db))
    }
    defer { sqlite3_finalize(s) }
    while true {
        let rc = sqlite3_step(s)
        if rc == SQLITE_ROW { row(s) } else if rc == SQLITE_DONE { return nil } else {
            return String(cString: sqlite3_errmsg(db))
        }
    }
}

func text(_ s: OpaquePointer, _ i: Int32) -> String? {
    guard let c = sqlite3_column_text(s, i) else { return nil }
    return String(cString: c)
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]

func append<T: Encodable>(_ record: T, to data: inout Data) {
    guard let line = try? encoder.encode(record) else { fail("encode failed") }
    data.append(line)
    data.append(0x0A)
}

// MARK: - Contacts (best effort)

struct ContactRecord: Encodable {
    let type = "contact"
    let uid: String
    let first: String?
    let last: String?
    let nickname: String?
    let org: String?
    let title: String?
    let birthday: Double?  // seconds since 2001-01-01; year 1604 means no year
    let me: Bool
    var phones: [String] = []
    var emails: [String] = []
}

struct ErrorRecord: Encodable {
    let type = "error"
    let source: String
    let message: String
}

/// The root Contacts database and one per account (iCloud, Google, ...) under Sources/.
func addressBookDatabases() -> [String] {
    var paths = [addressBookDir + "/AddressBook-v22.abcddb"]
    let sources = addressBookDir + "/Sources"
    let names = (try? FileManager.default.contentsOfDirectory(atPath: sources)) ?? []
    for name in names.sorted() where !name.hasPrefix(".") {
        paths.append(sources + "/" + name + "/AddressBook-v22.abcddb")
    }
    return paths.filter { FileManager.default.fileExists(atPath: $0) }
}

func readContacts(_ path: String) -> ([ContactRecord], String?) {
    let (opened, err) = openReadOnly(path)
    guard let db = opened else { return ([], err) }
    defer { sqlite3_close(db) }
    var cards: [Int64: ContactRecord] = [:]
    let cardError = query(
        db,
        """
        SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION, ZJOBTITLE,
               ZBIRTHDAY, ZCONTAINERWHERECONTACTISME IS NOT NULL
        FROM ZABCDRECORD
        WHERE ZUNIQUEID IS NOT NULL
          AND coalesce(ZFIRSTNAME, ZLASTNAME, ZORGANIZATION) IS NOT NULL
        """
    ) { s in
        guard let uid = text(s, 1) else { return }
        let bday = sqlite3_column_type(s, 7) == SQLITE_NULL ? nil : sqlite3_column_double(s, 7)
        cards[sqlite3_column_int64(s, 0)] = ContactRecord(
            uid: uid, first: text(s, 2), last: text(s, 3), nickname: text(s, 4),
            org: text(s, 5), title: text(s, 6), birthday: bday,
            me: sqlite3_column_int(s, 8) != 0)
    }
    if let e = cardError { return ([], e) }
    let phoneError = query(
        db, "SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER WHERE ZFULLNUMBER IS NOT NULL"
    ) { s in
        if let v = text(s, 1) { cards[sqlite3_column_int64(s, 0)]?.phones.append(v) }
    }
    let emailError = query(
        db, "SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZADDRESS IS NOT NULL"
    ) { s in
        if let v = text(s, 1) { cards[sqlite3_column_int64(s, 0)]?.emails.append(v) }
    }
    let sorted = cards.keys.sorted().compactMap { cards[$0] }
    return (sorted, phoneError ?? emailError)
}

var contacts = Data()
var contactCount = 0
let databases = addressBookDatabases()
if databases.isEmpty {
    append(ErrorRecord(source: "contacts", message: "no Contacts database found"), to: &contacts)
}
for path in databases {
    let (cards, err) = readContacts(path)
    for c in cards { append(c, to: &contacts) }
    contactCount += cards.count
    if let e = err {
        warn("contacts: \(e)")
        append(ErrorRecord(source: "contacts", message: e), to: &contacts)
    }
}
writeInbox("contacts.jsonl", contacts)

// MARK: - Messages

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

let (chatDB, openError) = openReadOnly(chatPath)
guard let chat = chatDB else {
    fail("cannot open chat.db: \(openError ?? "unknown error"). "
        + "Grant Full Disk Access to this binary; see `lab radar doctor`.", 77)
}

func mustQuery(_ sql: String, _ row: (OpaquePointer) -> Void) {
    if let msg = query(chat, sql, row) {
        let code: Int32 = msg.contains("authoriz") || msg.contains("unable to open") ? 77 : 1
        fail("query failed: \(msg)", code)
    }
}

var members: [String: [String]] = [:]
mustQuery(
    """
    SELECT c.guid, h.id
    FROM chat c
    JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
    JOIN handle h ON h.ROWID = chj.handle_id
    ORDER BY c.guid, h.id
    """
) { s in
    if let c = text(s, 0), let handle = text(s, 1) { members[c, default: []].append(handle) }
}

var messages = Data()
for (c, handles) in members.sorted(by: { $0.key < $1.key }) {
    append(ChatRecord(chat: c, members: handles), to: &messages)
}

// Snippets build: text for the newest message per chat, direction and sender only. That
// covers the newest interaction per contact, which is all sync keeps; every other
// message leaves chat.db without its text.
#if RADAR_SNIPPETS
    var snippetRows = Set<Int64>()
    mustQuery(
        """
        SELECT m.ROWID, max(m.date)
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        WHERE m.associated_message_type = 0 AND m.item_type = 0
        GROUP BY cmj.chat_id, m.is_from_me, m.handle_id
        """
    ) { s in snippetRows.insert(sqlite3_column_int64(s, 0)) }
#endif

// Regular messages only: no tapbacks or edits (associated_message_type), no
// group-membership events (item_type).
mustQuery(
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
    guard let guid = text(s, 1), let c = text(s, 5) else { return }
    var snippet: String? = nil
    #if RADAR_SNIPPETS
        if snippetRows.contains(sqlite3_column_int64(s, 0)) {
            snippet = text(s, 7).map { String($0.prefix(maxSnippet)) }
        }
    #endif
    append(
        MessageRecord(
            rowid: sqlite3_column_int64(s, 0),
            guid: guid,
            from_me: sqlite3_column_int(s, 2) != 0,
            date: sqlite3_column_int64(s, 3),
            sender: text(s, 4),
            chat: c,
            service: text(s, 6),
            text: snippet
        ), to: &messages)
}
sqlite3_close(chat)
writeInbox("messages.jsonl", messages)

close(dirFD)
close(radarFD)
close(baseFD)
print(
    "radar-messages-export: \(members.count) chats, \(contactCount) contacts "
        + "from \(databases.count) Contacts databases")
