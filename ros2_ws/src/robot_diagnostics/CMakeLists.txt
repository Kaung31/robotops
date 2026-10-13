cmake_minimum_required(VERSION 3.16)
project(robot_diagnostics)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE
      RelWithDebInfo
      CACHE STRING "Build type" FORCE)
endif()
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME})
find_package(rclcpp REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
add_executable(freshness_monitor src/freshness_monitor.cpp)
target_compile_features(freshness_monitor PRIVATE cxx_std_17)
target_compile_options(freshness_monitor PRIVATE -Wall -Wextra -Wpedantic)
target_include_directories(freshness_monitor PRIVATE include)
ament_target_dependencies(freshness_monitor rclcpp rcl_interfaces
                          diagnostic_msgs nav_msgs sensor_msgs)
install(TARGETS freshness_monitor DESTINATION lib/${PROJECT_NAME})
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(diagnostics_freshness test/test_freshness.py)
  ament_add_pytest_test(
    diagnostics_ros
    test/diagnostics_integration.py
    TIMEOUT
    60
    ENV
    ROS_DOMAIN_ID=187
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  add_executable(policy_trace test/policy_trace.cpp)
  target_compile_features(policy_trace PRIVATE cxx_std_17)
  target_include_directories(policy_trace PRIVATE include)
  ament_add_pytest_test(diagnostics_parity test/policy_parity.py ENV
                        ROBOTOPS_POLICY_TRACE=$<TARGET_FILE:policy_trace>)
endif()
ament_package()
