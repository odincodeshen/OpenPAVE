# Third-Party Notices

This project includes and depends on third-party components. Each component retains its original license and attribution.

## NVIDIA-AI-IOT live-vlm-webui

- Location: `ui/` submodule
- Upstream: `NVIDIA-AI-IOT/live-vlm-webui`
- OpenPAVE fork: `odincodeshen/live-vlm-webui`
- License: Apache License 2.0
- Notes: OpenPAVE currently uses an OpenPAVE-maintained fork of `live-vlm-webui` for the UI/backend path, including the `/pave` console integration.

OpenPAVE-specific changes do not imply NVIDIA endorsement, sponsorship, or official product alignment.

Future work will decouple the default OpenPAVE console from `live-vlm-webui` while preserving attribution and optional compatibility where useful.

## Hiwonder PuppyPi — `puppy_control_msgs`

- Location: `third_party/puppy_control_msgs`
- Upstream: Hiwonder PuppyPi, branch `ros2`, path `src/driver/puppy_control_msgs`
- License: Apache License 2.0
- Modification status: Unmodified
- Notes: Used to build a ROS 2 CLI Docker image that recognizes PuppyPi custom message types.
