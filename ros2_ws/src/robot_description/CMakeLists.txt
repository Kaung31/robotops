cmake_minimum_required(VERSION 3.16)
project(robot_description)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch urdf
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  find_package(launch_testing_ament_cmake REQUIRED)
  ament_add_pytest_test(description_model test/test_description.py)
  add_launch_test(test/description_launch.py TIMEOUT 90)
endif()

ament_package()
