cmake_minimum_required(VERSION 3.16)
project(mission_manager)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS scripts/mission_server DESTINATION lib/${PROJECT_NAME})
install(
  DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(mission_validation test/test_mission_validation.py)
  ament_add_pytest_test(recording_preparation
                        test/test_recording_preparation.py)
  ament_add_pytest_test(mission_integration test/mission_integration.py TIMEOUT
                        240 ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  ament_add_pytest_test(mission_launch_validation
                        test/mission_launch_validation.py)
  option(ROBOTOPS_MISSION_SIM_TESTS
         "Run recorded mission against Gazebo and Nav2" OFF)
  if(ROBOTOPS_MISSION_SIM_TESTS)
    ament_add_pytest_test(
      mission_system
      test/mission_system.py
      TIMEOUT
      300
      ENV
      ROS_DOMAIN_ID=150
      ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
      LIBGL_ALWAYS_SOFTWARE=1)
  endif()
endif()
ament_package()
