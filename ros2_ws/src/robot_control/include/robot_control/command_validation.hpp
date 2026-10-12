#pragma once

#include <cmath>
#include <cstdint>
#include <string_view>

#include "geometry_msgs/msg/twist_stamped.hpp"

namespace robot_control
{
struct CommandLimits
{
  double max_age;
  double future_tolerance;
};

inline std::string_view command_error(const geometry_msgs::msg::TwistStamped &command,
                                      int64_t now_ns, const CommandLimits &limits)
{
  const auto &stamp = command.header.stamp;
  if (now_ns <= 0 || stamp.sec < 0 || stamp.nanosec >= 1000000000U ||
      (stamp.sec == 0 && stamp.nanosec == 0))
  {
    return "invalid or uninitialized ROS timestamp";
  }
  const int64_t stamp_ns = static_cast<int64_t>(stamp.sec) * 1000000000LL + stamp.nanosec;
  const double age = static_cast<double>(now_ns - stamp_ns) / 1e9;
  if (age > limits.max_age || age < -limits.future_tolerance)
  {
    return "command timestamp is stale or in the future";
  }
  if (command.header.frame_id != "base_link")
  {
    return "command frame must be base_link";
  }
  const auto &twist = command.twist;
  if (!std::isfinite(twist.linear.x) || !std::isfinite(twist.angular.z) || twist.linear.y != 0.0 ||
      twist.linear.z != 0.0 || twist.angular.x != 0.0 || twist.angular.y != 0.0)
  {
    return "command must contain finite planar velocity";
  }
  return {};
}
} // namespace robot_control
