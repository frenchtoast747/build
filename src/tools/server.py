import array
import json
import os
import struct

from base64 import b64encode
from BaseHTTPServer import HTTPServer
from SimpleHTTPServer import SimpleHTTPRequestHandler
from hashlib import sha1
from SocketServer import ThreadingMixIn
from urlparse import urlparse


MAGIC_STRING = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class HttpServer(ThreadingMixIn, HTTPServer):
    def __init__(self, address, handler_class, current_project, manager, index_file):
        HTTPServer.__init__(self, address, handler_class)
        self.current_project = current_project
        self.manager = manager
        self.index_file = index_file


class HttpHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.websocket_mode = False
        SimpleHTTPRequestHandler.__init__(self, *args, **kwargs)

    def do_GET(self):
        self.current_project = self.server.current_project
        self.manager = self.server.manager
        if (self.headers.dict.get('connection') == 'Upgrade'
            and self.headers.dict.get('upgrade', '').lower() == 'websocket'):
            print 'Upgrading HTTP to websocket connection'
            self.websocket_mode = True
            self.websocket_handshake()
            self.manager.enable_events(True, self)
            self.serve()
        elif self.path == '/':
            self.send_response(200)
            self.end_headers()
            with open(self.server.index_file, 'rb') as f:
                self.wfile.write(f.read())
        else:
            path = os.path.abspath(os.path.dirname(self.server.index_file))
            path = os.path.normpath(path + self.path)
            path = urlparse(path).path
            if not os.path.exists(path):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(path))
            self.end_headers()
            with open(path, 'rb') as f:
                self.wfile.write(f.read())

    def finish(self):
        # when in websocket mode, don't close the connection.
        # This will block the server if it doesn't use the ThreadingMixIn
        if not self.websocket_mode:
            SimpleHTTPRequestHandler.finish(self)

    def websocket_handshake(self):
        secret_key = self.headers.dict.get('sec-websocket-key', '')
        hash = sha1()
        hash.update(secret_key + MAGIC_STRING)
        accept = b64encode(hash.digest())
        response = [
            'HTTP/1.1 101 Switching Protocols',
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Sec-WebSocket-Accept: ' + accept,
            '', '',
        ]
        self.request.sendall('\r\n'.join(response))

    def handle_data(self, data):
        pass

    def serve(self):
        while True:
            data = Frame.unpack(self.connection)
            if data is None or data == '\x03\xE9':
                self.quit()
                break
            self.handle_data(data)

    def quit(self):
        self.request.close()

    def send(self, data):
        self.write(data)

    def write(self, data):
        if isinstance(data, (list, tuple, set, dict)):
            data = json.dumps(data)
        data = data.strip()
        if data:
            self.wfile.write(Frame.pack(data))
            self.wfile.flush()

    def flush(self):
        self.wfile.flush()


class Frame(object):
    """
    WebSocket Frame Reference

         0                   1                   2                   3
         0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        +-+-+-+-+-------+-+-------------+-------------------------------+
        |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
        |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
        |N|V|V|V|       |S|             |   (if payload len==126/127)   |
        | |1|2|3|       |K|             |                               |
        +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
        |     Extended payload length continued, if payload len == 127  |
        + - - - - - - - - - - - - - - - +-------------------------------+
        |                               |Masking-key, if MASK set to 1  |
        +-------------------------------+-------------------------------+
        | Masking-key (continued)       |          Payload Data         |
        +-------------------------------- - - - - - - - - - - - - - - - +
        :                     Payload Data continued ...                :
        + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
        |                     Payload Data continued ...                |
        +---------------------------------------------------------------+
    """
    OP_CONTINUE = 0x0
    OP_TEXT      = 0x1
    OP_BINARY    = 0x2

    @staticmethod
    def unpack(socket):
        data = socket.recv(2)
        unpacked = struct.unpack('BB', data)
        fin = unpacked[0] & 0x80
        rsv1 = unpacked[0] & 0x40
        rsv2 = unpacked[0] & 0x20
        rsv3 = unpacked[0] & 0x10
        opcode = unpacked[0] & 0x0f
        payload_sz = unpacked[1] & 0x7f
        has_mask = bool(unpacked[1] & 0x80)

        if payload_sz == 126:
            payload_sz = socket.recv(2)
            payload_sz = struct.unpack('!H', payload_sz)[0]
        elif payload_sz == 127:
            raise Exception('TODO: handle data larger than 2**16 bytes.')
        mask = None
        if has_mask:
            mask = socket.recv(4)
        data = socket.recv(payload_sz)
        data = Frame.unmask(mask, data)
        return data

    @staticmethod
    def unmask(mask, data):
        if mask is None:
            return data
        mask = array.array('B', mask)
        data = array.array('B', data)
        for idx, old_byte in enumerate(data):
            data[idx] = old_byte ^ mask[idx % 4]
        return data.tostring()

    @staticmethod
    def pack(data, fin=1, rsv1=0, rsv2=0, rsv3=0, opcode=OP_TEXT):
        header = b''
        sz = len(data)
        header += struct.pack(
            '!B', (
              (fin << 7)
            | (rsv1 << 6)
            | (rsv2 << 5)
            | (rsv3 << 4)
            | opcode
            )
        )
        # ignore the mask bit since it's not required by the server
        if sz < 126:
            header += struct.pack('!B', sz)
        elif sz <= 2 ** 16:
            # 126 says to check the next 2 bytes for the payload sz
            header += struct.pack('!B', 126) + struct.pack('!H', sz)
        elif sz > 2 ** 16:
            header += struct.pack('!B', 127) + struct.pack('!Q', sz)

        data = data.encode('utf-8')
        return header + data
