cmake_minimum_required(VERSION 3.8)
project(fault_injection)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(action_msgs REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(robotops_interfaces REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(OpenSSL REQUIRED)
add_executable(scan_fault_relay src/scan_fault_relay.cpp)
target_compile_features(scan_fault_relay PRIVATE cxx_std_17)
target_compile_options(scan_fault_relay PRIVATE -Wall -Wextra -Wpedantic)
target_include_directories(scan_fault_relay PRIVATE include)
ament_target_dependencies(
  scan_fault_relay
  rclcpp
  rcl_interfaces
  sensor_msgs
  action_msgs
  nav2_msgs
  robotops_interfaces)
target_link_libraries(scan_fault_relay nlohmann_json::nlohmann_json
                      OpenSSL::Crypto)
install(TARGETS scan_fault_relay DESTINATION lib/${PROJECT_NAME})
install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(fault_routing_launch test/routing_launch.py)
  ament_add_pytest_test(fault_probe_evidence test/test_probe_evidence.py)
  ament_add_pytest_test(fault_routing_evidence test/test_routing_evidence.py)
  ament_add_pytest_test(fault_timing_evidence test/test_timing_evidence.py)
  ament_add_gtest(fault_policy test/policy_test.cpp test/owned_policy_test.cpp
                  test/input_watchdog_test.cpp)
  target_compile_features(fault_policy PRIVATE cxx_std_17)
  target_include_directories(fault_policy PRIVATE include)
  ament_add_pytest_test(
    fault_transport
    test/transport.py
    TIMEOUT
    120
    ENV
    ROS_DOMAIN_ID=188
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
endif()
ament_package()
