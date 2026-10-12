#include "action_msgs/msg/goal_status_array.hpp"
#include "fault_injection/input_watchdog.hpp"
#include "fault_injection/owned_policy.hpp"
#include "fault_injection/policy.hpp"
#include "nav2_msgs/action/navigate_to_pose.hpp"
#include "rclcpp/rclcpp.hpp"
#include "robotops_interfaces/msg/fault_event.hpp"
#include "robotops_interfaces/msg/fault_lifecycle_event.hpp"
#include "robotops_interfaces/srv/fault_control_v2.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include <atomic>
#include <chrono>
#include <cmath>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <nlohmann/json.hpp>
#include <openssl/evp.h>
#include <random>
#include <sstream>
#include <unistd.h>

namespace fault_injection
{
using Json = nlohmann::json;
std::string digest(const std::string &bytes)
{
  unsigned char hash[EVP_MAX_MD_SIZE];
  unsigned int size = 0;
  if (EVP_Digest(bytes.data(), bytes.size(), hash, &size, EVP_sha256(), nullptr) != 1)
    throw std::runtime_error("SHA256 failed");
  std::ostringstream result;
  for (unsigned int i = 0; i < size; ++i)
    result << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(hash[i]);
  return result.str();
}
void write_file(const std::filesystem::path &path, const std::string &bytes)
{
  std::ofstream file(path, std::ios::binary);
  file.exceptions(std::ios::badbit | std::ios::failbit);
  file << bytes;
  file.flush();
}
class Relay : public rclcpp::Node
{
public:
  Relay() : Node("scan_fault_relay", rclcpp::NodeOptions().use_clock_thread(false))
  {
    if (parameter<std::string>("mode", "") != "sim" || !get_parameter("use_sim_time").as_bool())
      throw std::invalid_argument("fault relay requires explicit mode=sim and use_sim_time=true");
    experiment_ = parameter<std::string>("experiment_id", "");
    trial_ = parameter<std::string>("trial_id", "");
    const auto kind = parameter<std::string>("fault_type", "");
    const double delay = parameter("delay_seconds", 0.0);
    const double duration = parameter("duration_seconds", 0.0);
    const double severity = parameter("severity", 1.0);
    if (!std::isfinite(delay) || !std::isfinite(duration) || delay < 0 || delay > 3600 ||
        duration < 1e-9 || duration > 60 || severity != 1.0)
      throw std::invalid_argument(
          "finite delay [0,3600], duration [1e-9,60], severity=1 required");
    const auto input = get_node_topics_interface()->resolve_topic_name("scan_input");
    const auto output = get_node_topics_interface()->resolve_topic_name("scan_output");
    if (input == output ||
        output == get_node_topics_interface()->resolve_topic_name("fault_events") ||
        input == get_node_topics_interface()->resolve_topic_name("fault_events"))
      throw std::invalid_argument("resolved input, output and event topics must be distinct");
    Plan plan{experiment_, trial_, kind, static_cast<int64_t>(delay * 1e9),
              static_cast<int64_t>(duration * 1e9)};
    const auto lifecycle = parameter<std::string>("lifecycle_mode", "standalone_v1");
    if (lifecycle != "standalone_v1" && lifecycle != "owned_v2")
      throw std::invalid_argument("unknown lifecycle_mode");
    owned_mode_ = lifecycle == "owned_v2";
    const double input_timeout = parameter("input_timeout_seconds", 0.0);
    const double input_startup = parameter("input_startup_seconds", 15.0);
    if (!std::isfinite(input_timeout) || !std::isfinite(input_startup) || input_timeout < 0 ||
        (input_timeout > 0 && input_timeout < 0.001) || input_timeout > 30 ||
        input_startup < 0.001 || input_startup > 60 || (input_timeout > 0 && !owned_mode_))
      throw std::invalid_argument("input watchdog requires bounded deadlines and owned_v2");
    input_watchdog_ =
        std::make_unique<InputWatchdog>(static_cast<int64_t>(input_timeout * 1e9),
                                        static_cast<int64_t>(input_startup * 1e9), wall_ns());
    if (owned_mode_)
    {
      auto seconds = [this](const std::string &name, double fallback, double maximum)
      {
        const auto value = parameter(name, fallback);
        if (!std::isfinite(value) || value < 0.001 || value > maximum)
          throw std::invalid_argument("invalid wall deadline: " + name);
        return static_cast<int64_t>(value * 1e9);
      };
      owned_ = std::make_unique<OwnedPolicy>(plan, wall_ns(),
                                             seconds("wall_lease_seconds", 90.0, 120.0),
                                             seconds("recovery_seconds", 5.0, 30.0));
      guard_ = parameter<std::string>("recovery_guard_path", "");
      if (!guard_.is_absolute())
        throw std::invalid_argument("absolute shared recovery_guard_path required");
      std::random_device random;
      session_ =
          digest(std::to_string(random()) + std::to_string(random()) + std::to_string(wall_ns()));
    }
    else
      policy_ = std::make_unique<Policy>(plan);
    directory_ = parameter<std::string>("evidence_directory", "");
    if (!directory_.is_absolute() || !std::filesystem::create_directory(directory_))
      throw std::invalid_argument(
          "evidence_directory must be an absolute new directory with existing parent");
    Json request = {{"schema_version", 1},
                    {"experiment_id", experiment_},
                    {"trial_id", trial_},
                    {"mode", "sim"},
                    {"target", "scan"},
                    {"fault_type", kind},
                    {"severity", severity},
                    {"delay_ns", plan.delay_ns},
                    {"duration_ns", plan.duration_ns},
                    {"input_topic", input},
                    {"output_topic", output},
                    {"schedule_origin", "first_positive_ros_clock_observed"}};
    if (owned_mode_)
    {
      request["schema_version"] = 2;
      request["schedule_origin"] = "owned_nav_executing_and_feedback";
      request["session_id"] = session_;
      request["wall_lease_seconds"] = get_parameter("wall_lease_seconds").as_double();
      request["recovery_seconds"] = get_parameter("recovery_seconds").as_double();
      if (input_watchdog_->enabled())
      {
        request["input_timeout_seconds"] = input_timeout;
        request["input_startup_seconds"] = input_startup;
      }
    }
    auto bytes = request.dump() + "\n";
    plan_hash_ = digest(bytes);
    write_file(directory_ / "plan.json", bytes);
    events_.open(directory_ / "events.jsonl", std::ios::binary);
    events_.exceptions(std::ios::badbit | std::ios::failbit);
    // use_sim_time is declared by rclcpp; forbid changing it after startup too.
    immutable_ = add_on_set_parameters_callback(
        [](const auto &)
        {
          rcl_interfaces::msg::SetParametersResult result;
          result.successful = false;
          result.reason = "fault plan and clock configuration are immutable";
          return result;
        });
    rcl_jump_threshold_t threshold{};
    threshold.on_clock_change = true;
    threshold.min_backward.nanoseconds = -1;
    jump_ = get_clock()->create_jump_callback(
        nullptr, [this](const auto &) { jumped_.store(true); }, threshold);
    if (owned_mode_)
    {
      // Never remove a pre-existing lock. A killed/uncertain predecessor needs review.
      int fd = ::open(guard_.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
      if (fd < 0)
        throw std::runtime_error("recovery guard exists or cannot be acquired; recovery required");
      ::close(fd);
      write_file(guard_, session_ + "\n");
    }
    publisher_ =
        create_publisher<sensor_msgs::msg::LaserScan>("scan_output", rclcpp::SensorDataQoS());
    evidence_ = create_publisher<robotops_interfaces::msg::FaultEvent>(
        "fault_events", rclcpp::QoS(32).reliable().transient_local());
    if (owned_mode_)
    {
      lifecycle_evidence_ = create_publisher<robotops_interfaces::msg::FaultLifecycleEvent>(
          "fault_lifecycle_events", rclcpp::QoS(32).reliable().transient_local());
      control_ = create_service<robotops_interfaces::srv::FaultControlV2>(
          "fault_control",
          [this](robotops_interfaces::srv::FaultControlV2::Request::SharedPtr request,
                 robotops_interfaces::srv::FaultControlV2::Response::SharedPtr response)
          {
            const auto now = get_clock()->now().nanoseconds();
            owned_->tick(now, wall_ns(), jumped_.exchange(false));
            const bool identity =
                request->experiment_id == experiment_ && request->trial_id == trial_ &&
                request->plan_sha256 == plan_hash_ && request->session_id == session_ &&
                request->clock_epoch == owned_->epoch();
            bool accepted = false;
            if (identity)
            {
              if (request->operation == 1)
                accepted = request->nav_goal_id.empty() &&
                           owned_->arm(request->mission_id, now, wall_ns());
              else if (request->operation == 2)
              {
                accepted = owned_->bind(request->mission_id, request->nav_goal_id, now, wall_ns());
                if (accepted)
                  subscribe_status(); // fetch current durable status, even if sent before binding
              }
              else if (request->operation == 3 &&
                       (owned_->mission().empty() || request->mission_id == owned_->mission()))
              {
                owned_->stop(now, wall_ns(), "owner_stop");
                accepted = true;
              }
            }
            drain();
            response->accepted = accepted;
            response->state = owned_->state();
            response->recovery_verified = owned_->verified();
            response->reason =
                accepted ? "accepted" : "identity, state, epoch or operation rejected";
          });
      subscribe_status();
      feedback_ = create_subscription<Feedback>(
          "navigate_to_pose/_action/feedback", rclcpp::QoS(10).reliable(),
          [this](Feedback::ConstSharedPtr message)
          {
            owned_->feedback(uuid_hex(message->goal_id.uuid), get_clock()->now().nanoseconds(),
                             wall_ns());
            drain();
          });
    }
    emit({"requested", 0, 0, 0, false});
    input_ = create_subscription<sensor_msgs::msg::LaserScan>(
        "scan_input", rclcpp::SensorDataQoS(),
        [this](sensor_msgs::msg::LaserScan::ConstSharedPtr message)
        {
          const auto received = wall_ns();
          // A late queued sample cannot silently heal an already expired lease.
          if (const auto failure = input_watchdog_->failure(received))
            throw std::runtime_error(failure);
          input_watchdog_->observe(received);
          const auto now = get_clock()->now().nanoseconds();
          const auto &stamp = message->header.stamp;
          auto ns =
              stamp.nanosec < 1000000000 ? int64_t(stamp.sec) * 1000000000 + stamp.nanosec : 0;
          effect_inflight_ = true;
          const auto action = owned_mode_
                                  ? owned_->sample(now, ns, wall_ns(), jumped_.exchange(false))
                                  : policy_->sample(now, ns, jumped_.exchange(false));
          if (!action.suppress)
          {
            if (action.freeze)
            {
              auto copy = *message;
              copy.header.stamp = rclcpp::Time(action.stamp_ns, RCL_ROS_TIME);
              publisher_->publish(copy);
            }
            else
            {
              publisher_->publish(*message);
              if (owned_mode_)
                owned_->forwarded(now, ns);
            }
          }
          effect_inflight_ = false;
          drain();
        });
    timer_ = create_wall_timer(
        std::chrono::milliseconds(20),
        [this, input, output]()
        {
          try
          {
            if (!rclcpp::ok())
              return;
            if (count_publishers(output) > 1)
              throw std::runtime_error(
                  "competing scan_output publisher: isolate raw input before using relay");
            if (input_watchdog_->enabled() && count_publishers(input) > 1)
              throw std::runtime_error("competing upstream scan publishers");
          }
          catch (const rclcpp::exceptions::RCLError &)
          {
            if (!rclcpp::ok())
              return; // context can close between the check and graph call
            throw;
          }
          if (const auto failure = input_watchdog_->failure(wall_ns()))
            throw std::runtime_error(failure);
          if (owned_mode_)
            owned_->tick(get_clock()->now().nanoseconds(), wall_ns(), jumped_.exchange(false));
          else
            policy_->tick(get_clock()->now().nanoseconds(), jumped_.exchange(false));
          drain();
        });
  }
  void finish(bool failed)
  {
    if (finished_)
      return;
    if (effect_inflight_)
      throw std::runtime_error("Local scan effect uncertain; evidence left unsealed");
    const auto now = get_clock()->now().nanoseconds();
    if (owned_mode_)
    {
      owned_->tick(now, wall_ns(), jumped_.exchange(false));
      owned_->stop(now, wall_ns(), failed ? "runtime_failure" : "shutdown");
    }
    else
    {
      policy_->tick(now, jumped_.exchange(false));
      policy_->finish(now, failed);
    }
    drain();
    events_.close();
    std::ifstream file(directory_ / "events.jsonl", std::ios::binary);
    file.exceptions(std::ios::badbit);
    const std::string bytes{std::istreambuf_iterator<char>(file),
                            std::istreambuf_iterator<char>()};
    write_file(directory_ / "seal.json", Json({{"schema_version", owned_mode_ ? 2 : 1},
                                               {"plan_sha256", plan_hash_},
                                               {"events_sha256", digest(bytes)},
                                               {"event_count", sequence_},
                                               {"termination", "closed"}})
                                                 .dump() +
                                             "\n");
    finished_ = true;
  }

private:
  template <typename T> T parameter(const std::string &name, const T &value)
  {
    rcl_interfaces::msg::ParameterDescriptor descriptor;
    descriptor.read_only = true;
    return declare_parameter<T>(name, value, descriptor);
  }
  void subscribe_status()
  {
    status_.reset();
    auto qos = rclcpp::QoS(1).reliable().transient_local();
    status_ = create_subscription<action_msgs::msg::GoalStatusArray>(
        "navigate_to_pose/_action/status", qos,
        [this](action_msgs::msg::GoalStatusArray::ConstSharedPtr message)
        {
          for (const auto &status : message->status_list)
            owned_->status(uuid_hex(status.goal_info.goal_id.uuid), status.status,
                           get_clock()->now().nanoseconds(), wall_ns());
          drain();
        });
  }
  static int64_t wall_ns()
  {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
  }
  template <typename UUID> static std::string uuid_hex(const UUID &uuid)
  {
    std::ostringstream result;
    for (auto value : uuid)
      result << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(value);
    return result.str();
  }
  void drain()
  {
    for (const auto &event : owned_mode_ ? owned_->drain() : policy_->drain())
      emit(event);
    if (owned_mode_ && owned_->verified() && !guard_released_)
    {
      // Preserve uncertainty if the marker changed; never unlink another owner.
      std::ifstream marker(guard_);
      std::string owner;
      std::getline(marker, owner);
      if (owner != session_ || !std::filesystem::remove(guard_))
        throw std::runtime_error("recovery guard ownership/removal failed");
      guard_released_ = true;
    }
  }
  void emit(const Event &event)
  {
    robotops_interfaces::msg::FaultEvent message;
    message.schema_version = owned_mode_ ? 2 : 1;
    message.experiment_id = experiment_;
    message.trial_id = trial_;
    message.plan_sha256 = plan_hash_;
    message.sequence = ++sequence_;
    message.state = event.state;
    message.ros_time_ns = event.ros_ns;
    message.clock_epoch = event.epoch;
    message.affected_samples = event.affected;
    message.applied_confirmed = event.confirmed;
    Json record = {{"schema_version", message.schema_version},
                   {"experiment_id", experiment_},
                   {"trial_id", trial_},
                   {"plan_sha256", plan_hash_},
                   {"sequence", sequence_},
                   {"state", event.state},
                   {"ros_time_ns", event.ros_ns},
                   {"clock_epoch", event.epoch},
                   {"affected_samples", event.affected},
                   {"applied_confirmed", event.confirmed}};
    if (owned_mode_)
    {
      record["mission_id"] = owned_->mission();
      record["nav_goal_id"] = owned_->nav();
      record["session_id"] = session_;
      const auto steady_now = wall_ns();
      record["wall_monotonic_ns"] = steady_now;
      robotops_interfaces::msg::FaultLifecycleEvent lifecycle;
      lifecycle.evidence = message;
      lifecycle.mission_id = owned_->mission();
      lifecycle.nav_goal_id = owned_->nav();
      lifecycle.session_id = session_;
      lifecycle.wall_monotonic_ns = steady_now;
      lifecycle.recovery_verified = owned_->verified();
      pending_lifecycle_ = lifecycle;
      record["recovery_verified"] = owned_->verified();
    }
    events_ << record.dump() << '\n';
    events_.flush();
    if (rclcpp::ok())
    {
      evidence_->publish(message);
      if (owned_mode_)
        lifecycle_evidence_->publish(pending_lifecycle_);
    }
  }
  using Feedback = nav2_msgs::action::NavigateToPose::Impl::FeedbackMessage;
  bool owned_mode_{false}, guard_released_{false};
  rclcpp::Publisher<robotops_interfaces::msg::FaultLifecycleEvent>::SharedPtr lifecycle_evidence_;
  robotops_interfaces::msg::FaultLifecycleEvent pending_lifecycle_;
  std::string session_;
  std::filesystem::path guard_;
  std::unique_ptr<OwnedPolicy> owned_;
  std::unique_ptr<InputWatchdog> input_watchdog_;
  rclcpp::Service<robotops_interfaces::srv::FaultControlV2>::SharedPtr control_;
  rclcpp::Subscription<action_msgs::msg::GoalStatusArray>::SharedPtr status_;
  rclcpp::Subscription<Feedback>::SharedPtr feedback_;
  std::atomic<bool> jumped_{false};
  bool finished_{false}, effect_inflight_{false};
  uint64_t sequence_{0};
  std::string experiment_, trial_, plan_hash_;
  std::filesystem::path directory_;
  std::ofstream events_;
  std::unique_ptr<Policy> policy_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr immutable_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr publisher_;
  rclcpp::Publisher<robotops_interfaces::msg::FaultEvent>::SharedPtr evidence_;
  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr input_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::JumpHandler::SharedPtr jump_;
};
} // namespace fault_injection
int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  int result = 0;
  std::shared_ptr<fault_injection::Relay> node;
  try
  {
    node = std::make_shared<fault_injection::Relay>();
    rclcpp::spin(node);
  }
  catch (const std::exception &error)
  {
    RCLCPP_ERROR(rclcpp::get_logger("scan_fault_relay"), "%s", error.what());
    result = 1;
  }
  try
  {
    if (node)
      node->finish(result != 0);
  }
  catch (const std::exception &error)
  {
    RCLCPP_ERROR(rclcpp::get_logger("scan_fault_relay"), "Evidence not sealed: %s", error.what());
    result = 1;
  }
  node.reset();
  rclcpp::shutdown();
  return result;
}
