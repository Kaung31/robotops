// Own shutdown ordering around the installed SLAM Toolbox lifecycle node.
#include <chrono>
#include <csignal>
#include <exception>
#include <memory>
#include <stdexcept>
#include <thread>

#include <lifecycle_msgs/msg/state.hpp>
#include <rclcpp/rclcpp.hpp>
#include <slam_toolbox/slam_toolbox_async.hpp>

namespace
{
volatile std::sig_atomic_t stop_requested = 0;

void request_stop(int) { stop_requested = 1; }
} // namespace

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv, rclcpp::InitOptions(), rclcpp::SignalHandlerOptions::None);
  std::signal(SIGINT, request_stop);
  std::signal(SIGTERM, request_stop);
  int result = 0;
  try
  {
    auto node = std::make_shared<slam_toolbox::AsynchronousSlamToolbox>(rclcpp::NodeOptions());
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(node->get_node_base_interface());
    while (!stop_requested && rclcpp::ok())
    {
      executor.spin_some(std::chrono::milliseconds(50));
      // Wall time ensures shutdown remains responsive when /clock is paused.
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    executor.remove_node(node->get_node_base_interface());
    using State = lifecycle_msgs::msg::State;
    if (node->get_current_state().id() == State::PRIMARY_STATE_ACTIVE)
    {
      if (node->deactivate().id() != State::PRIMARY_STATE_INACTIVE)
      {
        throw std::runtime_error("SLAM deactivation failed during shutdown");
      }
    }
    if (node->get_current_state().id() == State::PRIMARY_STATE_INACTIVE)
    {
      if (node->cleanup().id() != State::PRIMARY_STATE_UNCONFIGURED)
      {
        throw std::runtime_error("SLAM cleanup failed during shutdown");
      }
    }
    // Destructor joins workers before rclcpp::shutdown invalidates their clock.
    node.reset();
  }
  catch (const std::exception &error)
  {
    RCLCPP_ERROR(rclcpp::get_logger("slam_runner"), "SLAM failed: %s", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
