cmake_minimum_required(VERSION 3.16)
project(robot_navigation)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(slam_toolbox REQUIRED)
find_package(Boost REQUIRED COMPONENTS serialization)
find_package(TBB REQUIRED)
add_executable(slam_runner src/slam_runner.cpp)
target_compile_features(slam_runner PRIVATE cxx_std_17)
ament_target_dependencies(slam_runner rclcpp lifecycle_msgs slam_toolbox)
# The exported imported targets cover messages/services, not algorithm
# libraries. Resolve only the three implementation libraries used by this entry
# point.
foreach(library async_slam_toolbox toolbox_common kartoSlamToolbox)
  find_library(
    ${library}_PATH
    NAMES ${library}
    HINTS "${slam_toolbox_DIR}/../../../lib" REQUIRED)
  target_link_libraries(slam_runner ${${library}_PATH})
endforeach()
target_link_libraries(slam_runner Boost::serialization TBB::tbb)
install(TARGETS slam_runner DESTINATION lib/${PROJECT_NAME})
ament_python_install_package(${PROJECT_NAME})
install(
  DIRECTORY config launch rviz
  DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(slam_shutdown test/slam_shutdown.py TIMEOUT 180 ENV
                        ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST)
  ament_add_pytest_test(map_configuration test/test_map_configuration.py)
  ament_add_pytest_test(map_launch_validation test/map_launch_validation.py)
  ament_add_pytest_test(navigation_configuration
                        test/test_navigation_configuration.py)
  ament_add_pytest_test(navigation_launch_validation
                        test/navigation_launch_validation.py)
  option(ROBOTOPS_NAVIGATION_TESTS "Run autonomous navigation system tests" OFF)
  if(ROBOTOPS_NAVIGATION_TESTS)
    ament_add_pytest_test(
      navigation_system
      test/navigation_system.py
      TIMEOUT
      500
      ENV
      ROS_DOMAIN_ID=94
      ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
      LIBGL_ALWAYS_SOFTWARE=1)
  endif()
  option(ROBOTOPS_MAPPING_TESTS
         "Run headless map-save-restart-localization test" OFF)
  if(ROBOTOPS_MAPPING_TESTS)
    ament_add_pytest_test(
      mapping_system
      test/mapping_system.py
      TIMEOUT
      300
      ENV
      ROS_DOMAIN_ID=93
      ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
      LIBGL_ALWAYS_SOFTWARE=1)
  endif()
endif()
ament_package()
