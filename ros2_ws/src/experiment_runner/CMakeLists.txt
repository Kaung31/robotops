cmake_minimum_required(VERSION 3.16)
project(experiment_runner)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS scripts/experiment DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(experiment_model test/test_model.py)
  ament_add_pytest_test(experiment_validation test/test_validation.py)
  ament_add_pytest_test(experiment_contacts test/test_contacts.py)
  ament_add_pytest_test(experiment_ground_truth test/test_ground_truth.py)
  ament_add_pytest_test(experiment_integration test/experiment_integration.py
                        TIMEOUT 180 ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  option(ROBOTOPS_EXPERIMENT_SIM_TESTS
         "Run repeated recorded missions on Gazebo" OFF)
  if(ROBOTOPS_EXPERIMENT_SIM_TESTS)
    ament_add_pytest_test(
      experiment_system
      test/experiment_system.py
      TIMEOUT
      300
      ENV
      ROS_DOMAIN_ID=190
      ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
      LIBGL_ALWAYS_SOFTWARE=1)
  endif()
endif()
ament_package()
