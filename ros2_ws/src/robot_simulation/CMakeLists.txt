cmake_minimum_required(VERSION 3.16)
project(robot_simulation)

find_package(ament_cmake REQUIRED)
find_package(gz_sim_vendor REQUIRED)
find_package(gz-sim8 REQUIRED)
find_package(Threads REQUIRED)
find_package(rclcpp REQUIRED)
find_package(robotops_interfaces REQUIRED)
find_package(gz_plugin_vendor REQUIRED)
find_package(gz-plugin2 REQUIRED COMPONENTS register)
add_library(robotops_contact_evidence SHARED src/contact_evidence.cpp)
target_compile_features(robotops_contact_evidence PRIVATE cxx_std_17)
target_compile_options(robotops_contact_evidence PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(robotops_contact_evidence gz-sim8::gz-sim8 gz-plugin2::register)
ament_target_dependencies(robotops_contact_evidence rclcpp robotops_interfaces)
install(TARGETS robotops_contact_evidence DESTINATION lib)
add_executable(gazebo_runner src/gazebo_runner.cpp)
target_compile_features(gazebo_runner PRIVATE cxx_std_17)
target_compile_options(gazebo_runner PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(gazebo_runner gz-sim8::gz-sim8 Threads::Threads)
install(TARGETS gazebo_runner DESTINATION lib/${PROJECT_NAME})

install(
  DIRECTORY launch urdf worlds config
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(gazebo_runner_validation test/runner_validation.py)
  option(ROBOTOPS_GAZEBO_CONTACT_TESTS "Test independent physics contact evidence" OFF)
  if(ROBOTOPS_GAZEBO_CONTACT_TESTS)
    ament_add_pytest_test(gazebo_contacts test/contact_system.py TIMEOUT 90
      ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  endif()
  option(ROBOTOPS_GAZEBO_SHUTDOWN_TESTS "Test rendered Gazebo shutdown signals"
         OFF)
  if(ROBOTOPS_GAZEBO_SHUTDOWN_TESTS)
    ament_add_pytest_test(gazebo_shutdown test/gazebo_shutdown.py TIMEOUT 150)
  endif()
endif()
ament_package()
