#include <atomic>
#include <chrono>
#include <memory>
#include <utility>

#include "diagnostic_msgs/msg/diagnostic_array.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/imu.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"

#include "robot_diagnostics/freshness.hpp"

namespace robot_diagnostics
{
class FreshnessNode : public rclcpp::Node
{
public:
  FreshnessNode() : Node("robotops_diagnostics", rclcpp::NodeOptions().use_clock_thread(false))
  {
    streams_ = parameter<std::vector<std::string>>("enabled_streams", {"odom", "scan", "imu"});
    for (const auto &stream : streams_)
    {
      if (stream != "odom" && stream != "scan" && stream != "imu")
      {
        throw std::invalid_argument("enabled_streams must select odom, scan and/or imu");
      }
    }
    Policy policy;
    policy.warn_seconds = parameter("warn_seconds", policy.warn_seconds);
    policy.error_seconds = parameter("error_seconds", policy.error_seconds);
    policy.future_seconds = parameter("future_seconds", policy.future_seconds);
    policy.clock_stall_seconds = parameter("clock_stall_seconds", policy.clock_stall_seconds);
    monitor_ = std::make_unique<Monitor>(streams_, policy);
    const double period = parameter("publish_period_seconds", 0.2);
    if (!std::isfinite(period) || period < 1e-9 || period > 86400)
    {
      throw std::invalid_argument("publish_period_seconds must be in [1e-9, 86400]");
    }
    hardware_id_ = parameter<std::string>("hardware_id", "robotops");
    if (hardware_id_.find_first_not_of(" \t\r\n") == std::string::npos)
    {
      throw std::invalid_argument("hardware_id must be nonempty");
    }
    // Clock and sensor callbacks share the executor. Jump notification only
    // invalidates a generation; it never locks policy state inside the clock.
    rcl_jump_threshold_t threshold{};
    threshold.on_clock_change = true;
    threshold.min_backward.nanoseconds = -1;
    jump_ = get_clock()->create_jump_callback(
        nullptr, [this](const rcl_time_jump_t &) { generation_.fetch_add(1); }, threshold);
    publisher_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>(
        "diagnostics", rclcpp::QoS(10).reliable().durability_volatile());
    for (const auto &stream : streams_)
    {
      if (stream == "odom")
      {
        subscribe<nav_msgs::msg::Odometry>(stream, "odom");
      }
      if (stream == "scan")
      {
        subscribe<sensor_msgs::msg::LaserScan>(stream, "scan");
      }
      if (stream == "imu")
      {
        subscribe<sensor_msgs::msg::Imu>(stream, "imu/data");
      }
    }
    timer_ = create_wall_timer(std::chrono::nanoseconds(static_cast<int64_t>(period * 1e9)),
                               [this]() { publish(); });
  }

private:
  template <typename T> T parameter(const std::string &name, const T &value)
  {
    rcl_interfaces::msg::ParameterDescriptor descriptor;
    descriptor.read_only = true;
    return declare_parameter<T>(name, value, descriptor);
  }
  static double steady()
  {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
  }
  bool snapshot(int64_t &now, uint64_t &generation)
  {
    generation = generation_.load();
    now = get_clock()->now().nanoseconds();
    if (generation != generation_.load())
    {
      return false;
    }
    if (generation != seen_generation_)
    {
      monitor_->reset_clock();
      seen_generation_ = generation;
    }
    return true;
  }
  template <typename Message> void subscribe(const std::string &stream, const std::string &topic)
  {
    inputs_.push_back(create_subscription<Message>(
        topic, rclcpp::SensorDataQoS(),
        [this, stream](typename Message::ConstSharedPtr message)
        {
          int64_t now;
          uint64_t generation;
          if (!snapshot(now, generation))
          {
            return;
          }
          const auto &stamp = message->header.stamp;
          const int64_t ns =
              stamp.nanosec < 1000000000 ? int64_t(stamp.sec) * 1000000000 + stamp.nanosec : 0;
          monitor_->observe(stream, ns, now, steady());
        }));
  }
  void publish()
  {
    int64_t now;
    uint64_t generation;
    if (!snapshot(now, generation))
    {
      return;
    }
    const auto statuses = monitor_->evaluate(now, steady());
    diagnostic_msgs::msg::DiagnosticArray message;
    message.header.stamp = rclcpp::Time(now, get_clock()->get_clock_type());
    auto append = [&](const std::string &stream)
    {
      const auto &status = statuses.at(stream);
      diagnostic_msgs::msg::DiagnosticStatus item;
      item.name = stream == "clock" ? "robotops/clock" : "robotops/freshness/" + stream;
      item.hardware_id = hardware_id_;
      item.level = status.level;
      item.message = status.reason;
      for (const auto &[key, value] : status.values)
      {
        diagnostic_msgs::msg::KeyValue pair;
        pair.key = key;
        pair.value = value;
        item.values.push_back(std::move(pair));
      }
      message.status.push_back(std::move(item));
    };
    append("clock");
    for (const auto &stream : streams_)
    {
      append(stream);
    }
    if (generation == generation_.load())
    {
      publisher_->publish(message);
    }
  }
  // Policy runs only on the single-threaded executor. Jump handler is destroyed
  // before its generation counter.
  std::atomic<uint64_t> generation_{0};
  uint64_t seen_generation_{0};
  std::unique_ptr<Monitor> monitor_;
  std::string hardware_id_;
  std::vector<std::string> streams_;
  std::vector<rclcpp::SubscriptionBase::SharedPtr> inputs_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::JumpHandler::SharedPtr jump_;
};
} // namespace robot_diagnostics
int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  int result = 0;
  try
  {
    rclcpp::spin(std::make_shared<robot_diagnostics::FreshnessNode>());
  }
  catch (const std::exception &error)
  {
    RCLCPP_ERROR(rclcpp::get_logger("robotops_diagnostics"), "%s", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
