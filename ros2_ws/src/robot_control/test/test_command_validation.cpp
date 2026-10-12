#include <limits>

#include "robot_control/command_validation.hpp"
#include "gtest/gtest.h"

namespace
{
using robot_control::command_error;
constexpr robot_control::CommandLimits limits{0.3, 0.05};
constexpr int64_t now_ns = 10000000000LL;

auto valid_command()
{
  geometry_msgs::msg::TwistStamped command;
  command.header.stamp.sec = 10;
  command.header.frame_id = "base_link";
  command.twist.linear.x = 0.2;
  command.twist.angular.z = 0.5;
  return command;
}

TEST(CommandValidation, AcceptsCurrentPlanarVelocity)
{
  EXPECT_TRUE(command_error(valid_command(), now_ns, limits).empty());
}

TEST(CommandValidation, RejectsOldAndFutureTime)
{
  auto command = valid_command();
  command.header.stamp.sec = 9;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
  command.header.stamp.sec = 11;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
}

TEST(CommandValidation, RejectsUninitializedAndMalformedTime)
{
  auto command = valid_command();
  EXPECT_FALSE(command_error(command, 0, limits).empty());
  command.header.stamp.sec = 0;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
  command.header.stamp.sec = -1;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
  command.header.stamp.sec = 10;
  command.header.stamp.nanosec = 1000000000U;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
}

TEST(CommandValidation, RejectsNonfiniteValuesInEveryComponent)
{
  for (const double value :
       {std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity()})
  {
    for (int component = 0; component < 6; ++component)
    {
      auto command = valid_command();
      double *components[] = {&command.twist.linear.x,  &command.twist.linear.y,
                              &command.twist.linear.z,  &command.twist.angular.x,
                              &command.twist.angular.y, &command.twist.angular.z};
      *components[component] = value;
      EXPECT_FALSE(command_error(command, now_ns, limits).empty());
    }
  }
}

TEST(CommandValidation, RejectsWrongFrameAndNonplanarCommand)
{
  auto command = valid_command();
  command.header.frame_id = "odom";
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
  command = valid_command();
  command.twist.linear.y = 0.1;
  EXPECT_FALSE(command_error(command, now_ns, limits).empty());
}
} // namespace
