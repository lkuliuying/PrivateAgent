"""持续进程及其有界输出；输出游标与运行事件序号分别持久化。"""
from __future__ import annotations

from .store import encode, now

ACTIVE = {"starting", "running"}
OUTPUT_BYTES = 1024 * 1024
ACCOUNT_BYTES = 64 * 1024 * 1024


def create_schema(db):
    db.execute("CREATE TABLE managed_executions(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), session_id INTEGER NOT NULL, workspace_id INTEGER NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL)")
    db.execute("CREATE INDEX managed_executions_session ON managed_executions(session_id,status)")
    db.execute("CREATE TABLE execution_chunks(execution_id TEXT NOT NULL REFERENCES managed_executions(id), sequence INTEGER NOT NULL, stream TEXT NOT NULL, data TEXT NOT NULL, size INTEGER NOT NULL, host_sequence INTEGER NOT NULL, PRIMARY KEY(execution_id,sequence))")


class ExecutionStore:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def save(self, record):
        with self.store.transaction():
            self.db.execute("INSERT INTO managed_executions VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                            (record["execution_id"], record["run_id"], record["session_id"], record["workspace_id"], record["status"], encode(record)))

    def get(self, execution_id, session_id):
        row = self.db.execute("SELECT data FROM managed_executions WHERE id=? AND session_id=?", (execution_id, session_id)).fetchone()
        if row is None:
            raise ValueError("执行不存在或不属于当前会话")
        return self.store._unpack(row[0])

    def list(self, session_id):
        return [self.store._unpack(row[0]) for row in self.db.execute(
            "SELECT data FROM managed_executions WHERE session_id=? ORDER BY rowid DESC LIMIT 256", (session_id,))]

    def append(self, record, chunks):
        if not chunks:
            return
        with self.store.transaction():
            account_size = self.db.execute("SELECT COALESCE(SUM(size),0) FROM execution_chunks").fetchone()[0]
            for stream, data, host_sequence in chunks:
                size = len(data.encode("utf-8"))
                record["last_output_sequence"] += 1
                sequence = record["last_output_sequence"]
                record["total_output_bytes"] += size
                # 账号配额耗尽仍排空进程管道，并明确记下未保存的范围。
                if account_size + size > ACCOUNT_BYTES:
                    record["dropped_bytes"] += size
                    record["output_quota_exceeded"] = True
                    continue
                self.db.execute("INSERT INTO execution_chunks VALUES (?,?,?,?,?,?)",
                                (record["execution_id"], sequence, stream, data, size, host_sequence))
                account_size += size
            rows = self.db.execute("SELECT sequence,size FROM execution_chunks WHERE execution_id=? ORDER BY sequence DESC", (record["execution_id"],)).fetchall()
            retained = 0
            for sequence, size in rows:
                retained += size
                if retained > OUTPUT_BYTES or len(rows) > 512 and sequence <= rows[512][0]:
                    self.db.execute("DELETE FROM execution_chunks WHERE execution_id=? AND sequence=?", (record["execution_id"], sequence))
                    record["dropped_bytes"] += size
            self.save(record)

    def read(self, record, after=0, limit=32_000):
        if after < 0 or after > record["last_output_sequence"]:
            raise ValueError("输出游标超出可用范围")
        rows = self.db.execute("SELECT sequence,stream,data,host_sequence FROM execution_chunks WHERE execution_id=? AND sequence>? ORDER BY sequence LIMIT 128",
                               (record["execution_id"], after)).fetchall()
        chunks, size, cursor, gap = [], 0, after, False
        for sequence, stream, data, host_sequence in rows:
            if chunks and size + len(data.encode("utf-8")) > limit:
                break
            gap |= sequence != cursor + 1
            chunks.append({"sequence": sequence, "stream": stream, "data": data, "host_sequence": host_sequence})
            size += len(data.encode("utf-8"))
            cursor = sequence
        if not chunks and cursor < record["last_output_sequence"]:
            gap, cursor = True, record["last_output_sequence"]
        available = self.db.execute("SELECT MIN(sequence),MAX(sequence) FROM execution_chunks WHERE execution_id=?", (record["execution_id"],)).fetchone()
        return {**record, "chunks": chunks, "next_cursor": cursor, "gap": gap,
                "available_from": available[0], "available_to": available[1], "has_more": cursor < record["last_output_sequence"]}

    def recover(self):
        for (data,) in self.db.execute("SELECT data FROM managed_executions WHERE status IN ('starting','running')").fetchall():
            record = self.store._unpack(data)
            record.update(status="unknown", stopped=False, error="执行器重启，未恢复或重放进程", completed_at=now())
            record["state_version"] += 1
            self.save(record)
