cmake_minimum_required(VERSION 3.16)
project(robot_bringup)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY launch urdf
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  find_package(launch_testing_ament_cmake REQUIRED)
  ament_add_pytest_test(backend_models test/test_models.py)
  ament_add_pytest_test(launch_validation test/launch_validation.py)
  add_launch_test(test/control_launch.py ENV ROBOTOPS_TEST_MODE=mock TIMEOUT
                  120)
  option(ROBOTOPS_SIM_TESTS "Run headless Gazebo system tests" OFF)
  if(ROBOTOPS_SIM_TESTS)
    add_launch_test(
      test/control_launch.py
      ENV
      ROBOTOPS_TEST_MODE=sim
      TARGET
      sim_control
      TIMEOUT
      180)
  endif()
endif()

ament_package()
