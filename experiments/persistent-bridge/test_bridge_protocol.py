"""Unit tests for the bridge wire protocol (pure JSON, no ROS/socket). Run from this dir:

    python3 -m unittest test_bridge_protocol
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_protocol as bp  # noqa: E402


class EncodeDecodeTests(unittest.TestCase):
    def test_round_trip(self):
        msg = bp.make_request("r1", [{"op": "sleep", "sec": 0.1}])
        line = bp.encode(msg).decode().rstrip("\n")
        self.assertEqual(bp.decode(line), msg)

    def test_encode_is_one_newline_line(self):
        raw = bp.encode(bp.make_result("r1", True, []))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw.count(b"\n"), 1)

    def test_decode_bad_json_raises(self):
        with self.assertRaises(bp.ProtocolError):
            bp.decode("{not json")

    def test_decode_non_object_or_no_type_raises(self):
        with self.assertRaises(bp.ProtocolError):
            bp.decode("[1,2,3]")
        with self.assertRaises(bp.ProtocolError):
            bp.decode('{"id":"r1"}')  # no 'type'


class ValidateRequestTests(unittest.TestCase):
    def test_valid_sync_request(self):
        req = bp.make_request("r1", [
            {"op": "service", "service": "/x", "type": "std_srvs/srv/Empty", "data": {}},
            {"op": "sleep", "sec": 0.2},
        ])
        req_id, steps, timeout_ms = bp.validate_request(req)
        self.assertEqual(req_id, "r1")
        self.assertEqual(len(steps), 2)
        self.assertIsNone(timeout_ms)

    def test_timeout_ms_passed_through(self):
        req = bp.make_request("r1", [{"op": "sleep", "sec": 0}], timeout_ms=2500)
        _, _, timeout_ms = bp.validate_request(req)
        self.assertEqual(timeout_ms, 2500)

    def test_async_mode_reserved_but_rejected(self):
        req = bp.make_request("r2", [{"op": "sleep", "sec": 0}], mode=bp.MODE_ASYNC)
        with self.assertRaises(bp.ProtocolError) as ctx:
            bp.validate_request(req)
        self.assertEqual(ctx.exception.code, bp.E_UNSUPPORTED_MODE)

    def test_action_op_reserved_but_rejected_in_sync(self):
        req = bp.make_request("r3", [{"op": bp.OP_ACTION, "action": "/nav"}])
        with self.assertRaises(bp.ProtocolError) as ctx:
            bp.validate_request(req)
        self.assertEqual(ctx.exception.code, bp.E_UNSUPPORTED_OP)

    def test_missing_id_or_bad_steps(self):
        with self.assertRaises(bp.ProtocolError):
            bp.validate_request({"type": bp.T_REQUEST, "mode": "sync", "steps": []})
        with self.assertRaises(bp.ProtocolError):
            bp.validate_request({"type": bp.T_REQUEST, "id": "r", "steps": "nope"})

    def test_wrong_type(self):
        with self.assertRaises(bp.ProtocolError):
            bp.validate_request(bp.make_result("r", True, []))


class VersionPingErrorTests(unittest.TestCase):
    def test_all_builders_stamp_version(self):
        for msg in (bp.make_request("r", []), bp.make_result("r", True, []),
                    bp.make_error("r", "x"), bp.make_ping("p"), bp.make_pong("p", True)):
            self.assertEqual(msg["version"], bp.PROTOCOL_VERSION)

    def test_error_has_ok_false_and_code(self):
        err = bp.make_error("r", "nope", code=bp.E_UNSUPPORTED_MODE)
        self.assertFalse(err["ok"])
        self.assertEqual(err["code"], bp.E_UNSUPPORTED_MODE)

    def test_decode_bad_json_carries_code(self):
        with self.assertRaises(bp.ProtocolError) as ctx:
            bp.decode("{nope")
        self.assertEqual(ctx.exception.code, bp.E_BAD_JSON)

    def test_ping_pong_shape(self):
        self.assertEqual(bp.make_ping("p1")["type"], bp.T_PING)
        pong = bp.make_pong("p1", ready=True, detail={"services_ready": True})
        self.assertEqual(pong["type"], bp.T_PONG)
        self.assertTrue(pong["ready"])
        self.assertTrue(pong["detail"]["services_ready"])


class LineBufferTests(unittest.TestCase):
    def test_reassembles_split_and_glued_messages(self):
        buf = bp.LineBuffer()
        # a half message, then the rest + a full second message glued on
        out = list(buf.feed(b'{"type":"a"'))
        self.assertEqual(out, [])
        out = list(buf.feed(b'}\n{"type":"b"}\n'))
        self.assertEqual(out, ['{"type":"a"}', '{"type":"b"}'])

    def test_blank_lines_skipped_and_partial_held(self):
        buf = bp.LineBuffer()
        out = list(buf.feed(b"\n\n{\"type\":\"c\"}\n{\"partial\":"))
        self.assertEqual(out, ['{"type":"c"}'])  # trailing partial stays buffered
        out = list(buf.feed(b'1}\n'))
        self.assertEqual(out, ['{"partial":1}'])


if __name__ == "__main__":
    unittest.main()
