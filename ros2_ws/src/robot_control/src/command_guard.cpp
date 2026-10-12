#include <memory>
#include <stdexcept>

#include "rclcpp/rclcpp.hpp"
#include "robot_control/command_validation.hpp"

namespace robot_control
{
class CommandGuard : public rclcpp::Node
{
public:
  CommandGuard() : Node("command_guard")
  {
    limits_.max_age = declare_parameter("max_age", 0.3);
    limits_.future_tolerance = declare_parameter("future_tolerance", 0.05);
    if (!std::isfinite(limits_.max_age) || limits_.max_age <= 0.0 ||
        !std::isfinite(limits_.future_tolerance) || limits_.future_tolerance < 0.0)
    {
      throw std::invalid_argument(
          "max_age must be positive; future_tolerance must be nonnegative");
    }
    const auto qos = rclcpp::QoS(1).reliable().durability_volatile();
    publisher_ = create_publisher<geometry_msgs::msg::TwistStamped>("output", qos);
    subscription_ = create_subscription<geometry_msgs::msg::TwistStamped>(
        "input", qos,
        [this](geometry_msgs::msg::TwistStamped::ConstSharedPtr command)
        {
          const auto stamp = now();
          const auto error = command_error(*command, stamp.nanoseconds(), limits_);
          if (error.empty())
          {
            publisher_->publish(*command);
            return;
          }
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000, "Rejected command: %s",
                               error.data());
          // Invalid traffic can request a stop, never preserve a moving command.
          geometry_msgs::msg::TwistStamped stop;
          stop.header.stamp = stamp;
          stop.header.frame_id = "base_link";
          publisher_->publish(stop);
        });
  }

private:
  CommandLimits limits_{};
  rclcpp::Publisher<geometry_msgs::msg::TwistStamped>::SharedPtr publisher_;
  rclcpp::Subscription<geometry_msgs::msg::TwistStamped>::SharedPtr subscription_;
};
} // namespace robot_control

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  try
  {
    rclcpp::spin(std::make_shared<robot_control::CommandGuard>());
  }
  catch (const std::exception &error)
  {
    RCLCPP_FATAL(rclcpp::get_logger("command_guard"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
