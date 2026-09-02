"""Seam transport backends.

Each backend implements `pave_runtime.seam.SeamTransport` (`serve` / `send`) and **lazily imports
its own dependency** (zenoh / device-connect), so `pave_runtime.seam` stays dependency-free and a
deployment only pulls in the transport it actually selects. Registered in `pave_runtime.seam._BACKENDS`.
"""
