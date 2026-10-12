cmake_minimum_required(VERSION 3.16)
project(robot_control)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
add_executable(command_guard src/command_guard.cpp)
target_compile_features(command_guard PRIVATE cxx_std_17)
target_compile_options(command_guard PRIVATE -Wall -Wextra -Wpedantic)
target_include_directories(command_guard PRIVATE include)
ament_target_dependencies(command_guard rclcpp geometry_msgs)
install(TARGETS command_guard DESTINATION lib/${PROJECT_NAME})
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME})

install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(command_validation test/test_command_validation.cpp)
  target_compile_features(command_validation PRIVATE cxx_std_17)
  target_include_directories(command_validation PRIVATE include)
  ament_target_dependencies(command_validation geometry_msgs)
  ament_add_pytest_test(control_config test/test_configuration.py)
endif()

ament_package()
