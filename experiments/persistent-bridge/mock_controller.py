#!/usr/bin/env python3
"""Mock puppy_control — an rclpy node offering the services the bridge calls.

Lets B1 be validated on a plain host (RPi5 .13) with **no real robot**: it stands in for
puppy_control by answering the same service names with std_srvs (so no puppy_control_msgs needed).
The point of B1 is the bridge's latency/protocol, not the robot's behaviour — a trivial responder
is enough.

Run inside a ROS 2 container (FastDDS, same graph as the bridge):
    python3 mock_controller.py
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from std_srvs.srv import Empty, SetBool


class MockController(Node):
    def __init__(self) -> None:
        super().__init__("mock_puppy_control")
        self.create_service(SetBool, "/puppy_control/set_running", self._set_bool)
        self.create_service(SetBool, "/puppy_control/set_mark_time", self._set_bool)
        self.create_service(Empty, "/puppy_control/go_home", self._empty)
        self.get_logger().info(
            "mock puppy_control up · services: set_running / set_mark_time / go_home"
        )

    def _set_bool(self, request, response):
        response.success = True
        response.message = "ok"
        return response

    def _empty(self, request, response):
        return response


def main() -> None:
    rclpy.init()
    node = MockController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
