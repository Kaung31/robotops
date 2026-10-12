cmake_minimum_required(VERSION 3.16)
project(robotops_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
rosidl_generate_interfaces(
  ${PROJECT_NAME}
  "action/ExecuteMission.action"
  "msg/ContactPair.msg"
  "msg/ContactEvidence.msg"
  "msg/FaultEvent.msg"
  "msg/FaultLifecycleEvent.msg"
  "srv/FaultControlV2.srv"
  DEPENDENCIES
  geometry_msgs)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
