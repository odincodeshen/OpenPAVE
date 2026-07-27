# Brain–Body Architecture

Brain issues high-level intent; the body runs the real-time loop and fails safe
on disconnect. The two hosts talk over one zenoh fabric, and the zenoh router
runs on the brain host (DGX).

![Brain–Body Architecture](architecture-brain-body.svg)

- Solid = control path · dashed = optional · ★ = fail-safe
- `zenoh #1` = cross-host seam (router on DGX) · `zenoh #2` = `rmw_zenoh` inside the body
- Downlink = intent (`@rpc`) · uplink = state (`@emit`) · plus heartbeat
