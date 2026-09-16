"""Small adapter for HALCON's undocumented debug RPC.

Thrift binary protocol, unframed TCP, multiplexed session/debug/notifications.
Field IDs were reconstructed and tested against our own HDevEngine, not DAP.
"""
from thrift.protocol import TBinaryProtocol
from thrift.transport import TSocket, TTransport

BOOL, I32, STRING, STRUCT, LIST = 2, 8, 11, 12, 15


class DebugProtocolError(RuntimeError):
    def __init__(self, method, fields):
        self.method, self.fields = method, fields
        super().__init__(f"{method}: {fields!r}")


def read(p, kind, depth=0):
    if depth > 16:
        raise ValueError("RPC nesting limit exceeded")
    if kind == STRUCT:
        result = {}
        p.readStructBegin()
        for _ in range(256):
            _, typ, fid = p.readFieldBegin()
            if typ == 0:
                p.readStructEnd()
                return result
            result[fid] = (typ, read(p, typ, depth + 1))
            p.readFieldEnd()
        raise ValueError("RPC field limit exceeded")
    if kind == LIST:
        typ, size = p.readListBegin()
        if not 0 <= size <= 10000:
            raise ValueError("RPC list limit exceeded")
        result = [read(p, typ, depth + 1) for _ in range(size)]
        p.readListEnd()
        return result
    return {BOOL: p.readBool, I32: p.readI32, STRING: p.readBinary}[kind]()


def write(p, kind, value):
    if kind == STRUCT:
        p.writeStructBegin("")
        for fid, typ, val in value:
            p.writeFieldBegin("", typ, fid)
            write(p, typ, val)
            p.writeFieldEnd()
        p.writeFieldStop()
        p.writeStructEnd()
    elif kind == LIST:
        typ, values = value
        p.writeListBegin(typ, len(values))
        for val in values:
            write(p, typ, val)
        p.writeListEnd()
    else:
        if kind == STRING and isinstance(value, str):
            value = value.encode("utf-8")
        {BOOL: p.writeBool, I32: p.writeI32, STRING: p.writeBinary}[kind](value)


class DebugClient:
    """One persistent, sequential RPC connection to a locally owned engine."""
    def __init__(self, port):
        sock = TSocket.TSocket("127.0.0.1", port)
        sock.setTimeout(3000)
        self.transport = TTransport.TBufferedTransport(sock)
        self.transport.open()
        self.protocol = TBinaryProtocol.TBinaryProtocol(
            self.transport, string_length_limit=64 * 1024 * 1024,
            container_length_limit=10000)
        self.sequence = 0

    def call(self, method, fields=()):
        self.sequence += 1
        p = self.protocol
        p.writeMessageBegin(method, 1, self.sequence)
        write(p, STRUCT, fields)
        p.writeMessageEnd()
        self.transport.flush()
        name, typ, sequence = p.readMessageBegin()
        result = read(p, STRUCT)
        p.readMessageEnd()
        if sequence != self.sequence or name != method.split(":", 1)[1]:
            raise RuntimeError("RPC reply does not match request")
        if typ != 2 or 1 in result:
            raise DebugProtocolError(method, result)
        return result.get(0, (None, None))[1]

    def attach(self, session):
        credentials = ((1, STRING, ""), (2, STRING, session))
        if self.call("session:IsProtected"):
            raise RuntimeError("Password-protected debug servers are not supported")
        for method in ("session:StartDebugSession", "debug:Join", "notifications:Join"):
            if self.call(method, credentials) is not True:
                raise RuntimeError(f"{method} rejected")

    def event(self):
        # Timeout zero is a nonblocking dequeue, not an infinite wait.
        value = self.call("notifications:GetNotification", ((1, I32, 0),))
        return {"type": value[1][1], "reason": value[2][1],
                "thread": value[3][1].decode(), "context": value[4][1].decode()}

    def set_breakpoints(self, points):
        values = [((1, BOOL, bool(variable)), (2, STRING, proc),
                   (3, I32, line - 1), (4, STRING, variable)) for proc, line, variable in points]
        self.call("debug:SetBreakpoints", ((1, LIST, (STRUCT, values)),))

    def get_breakpoints(self, procedure):
        # The native list can contain duplicates (multiple loaded instances).
        return {(entry[2][1].decode(), 0 if entry[1][1] else entry[3][1] + 1,
                 entry[4][1].decode() if entry[1][1] else "")
                for entry in self.call("debug:GetProcBreakpoints", ((1, STRING, procedure),))}

    def close(self):
        self.transport.close()
