# Stable Runbook (MVP)

## PuppyPi side
1) Start the PuppyPi ROS2 controller:
```bash
cd /path/to/OpenPAVE
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
./scripts/start_puppypi_controller.sh
```

The script starts the `puppypi_ros2` container, refreshes the ROS2 daemon by default, and launches `puppy_control`.

Override defaults when needed:

```bash
PUPPYPI_CONTAINER=puppypi_ros2 ROS_DOMAIN_ID=0 ./scripts/start_puppypi_controller.sh
```

## DGX side
1) Export environment:
```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

2) Start Intent Ingress:
```bash
cd /path/to/OpenPAVE
python3 -m intent_ingress.server
```

3) Start Control Daemon:
```bash
cd /path/to/OpenPAVE
python3 -m control_daemon.daemon
```

## Common failure: FastDDS RTPS history error
Symptom: Robot stops responding even though messages appear to be delivered.
Log example:
`RTPS_READER_HISTORY Error ... cannot be resized`

Fix:
- Restart `puppy_control.launch.py`
- (Optional) `ros2 daemon stop/start`
