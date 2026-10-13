// Read-only Gazebo adapter. Never publishes control, odometry, or TF.
#include <algorithm>
#include <chrono>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include <gz/plugin/Register.hh>
#include <gz/sim/System.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/Collision.hh>
#include <gz/sim/components/ContactSensorData.hh>
#include <gz/sim/components/Name.hh>
#include <gz/sim/components/ParentEntity.hh>
#include <rclcpp/rclcpp.hpp>
#include <robotops_interfaces/msg/contact_evidence.hpp>

namespace robot_simulation
{
class ContactEvidence final : public gz::sim::System,
                              public gz::sim::ISystemConfigure,
                              public gz::sim::ISystemPreUpdate,
                              public gz::sim::ISystemPostUpdate
{
  using Frame = robotops_interfaces::msg::ContactEvidence;
  using Pair = robotops_interfaces::msg::ContactPair;
  using Entity = gz::sim::Entity;
  using ECM = gz::sim::EntityComponentManager;

public:
  void Configure(const Entity &entity, const std::shared_ptr<const sdf::Element> &sdf, ECM &,
                 gz::sim::EventManager &) override
  {
    model_ = entity;
    auto config = sdf->Clone();
    if (!config->HasElement("body") || !config->HasElement("support_body") ||
        !config->HasElement("floor"))
    {
      throw std::runtime_error("Contact evidence requires body/support_body/floor inventory");
    }
    for (auto e = config->GetElement("body"); e; e = e->GetNextElement("body"))
    {
      expected_.insert(e->Get<std::string>());
    }
    for (auto e = config->GetElement("support_body"); e; e = e->GetNextElement("support_body"))
    {
      support_.insert(e->Get<std::string>());
    }
    floor_ = config->Get<std::string>("floor");
    if (!std::includes(expected_.begin(), expected_.end(), support_.begin(), support_.end()))
    {
      throw std::runtime_error("Support bodies must belong to monitored inventory");
    }
    std::random_device random;
    std::ostringstream id;
    id << std::hex << random() << random() << random() << random();
    source_ = id.str();
    context_ = std::make_shared<rclcpp::Context>();
    context_->init(0, nullptr);
    auto options = rclcpp::NodeOptions()
                       .context(context_)
                       .start_parameter_services(false)
                       .start_parameter_event_publisher(false)
                       .enable_rosout(false);
    node_ = std::make_shared<rclcpp::Node>("contact_evidence", options);
    const auto topic = config->Get<std::string>("topic", "validation/contacts").first;
    publisher_ = node_->create_publisher<Frame>(topic, rclcpp::QoS(100).reliable());
  }

  ~ContactEvidence() override
  {
    if (context_)
    {
      context_->shutdown("Gazebo contact adapter stopped");
    }
  }

  void PreUpdate(const gz::sim::UpdateInfo &info, ECM &ecm) override
  {
    if (info.paused)
    {
      return;
    }
    bodies_.clear();
    ecm.Each<gz::sim::components::Collision>(
        [&](const Entity &entity, gz::sim::components::Collision *)
        {
          std::vector<std::string> parts;
          auto parent = entity;
          while (parent != gz::sim::kNullEntity && parent != model_)
          {
            auto name = ecm.Component<gz::sim::components::Name>(parent);
            auto ancestor = ecm.Component<gz::sim::components::ParentEntity>(parent);
            if (!name || !ancestor)
            {
              break;
            }
            parts.push_back(name->Data());
            parent = ancestor->Data();
          }
          if (parent == model_)
          {
            std::string name;
            for (auto i = parts.rbegin(); i != parts.rend(); ++i)
            {
              name += (name.empty() ? "" : "::") + *i;
            }
            bodies_[entity] = name;
          }
          return true;
        });
    for (const auto &[entity, name] : bodies_)
    {
      (void)name;
      if (!ecm.Component<gz::sim::components::ContactSensorData>(entity))
      {
        ecm.CreateComponent(entity, gz::sim::components::ContactSensorData());
      }
    }
  }

  void PostUpdate(const gz::sim::UpdateInfo &info, const ECM &ecm) override
  {
    if (info.paused || !publisher_)
    {
      return;
    }
    const auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count();
    const auto dt = std::chrono::duration_cast<std::chrono::nanoseconds>(info.dt).count();
    // Reset/regression invalidates this source permanently; a fresh model gets a new source.
    if (dt <= 0 || (last_ >= 0 && now - dt != last_))
    {
      broken_ = true;
    }
    if (steps_ == 0)
    {
      start_ = now - dt;
    }
    last_ = now;
    ++steps_;
    std::set<std::string> inventory;
    bool has_support = false;
    for (const auto &[entity, name] : bodies_)
    {
      inventory.insert(name);
      const auto data = ecm.Component<gz::sim::components::ContactSensorData>(entity);
      if (!data)
      {
        complete_ = false;
        continue;
      }
      for (const auto &contact : data->Data().contact())
      {
        auto other = contact.collision1().id() == entity ? contact.collision2().id()
                                                         : contact.collision1().id();
        auto other_name = gz::sim::scopedName(other, ecm, "::", false);
        const auto prefix = other_name.find("::");
        if (prefix != std::string::npos)
        {
          other_name.erase(0, prefix + 2);
        }
        if (support_.count(name) && other_name == floor_)
        {
          has_support = true;
          continue;
        }
        auto first = gz::sim::scopedName(entity, ecm, "::", false);
        auto second = gz::sim::scopedName(other, ecm, "::", false);
        if (second < first)
        {
          std::swap(first, second);
        }
        const auto key = std::make_pair(first, second);
        auto [entry, inserted] = contacts_.try_emplace(key);
        auto &pair = entry->second;
        if (inserted)
        {
          pair.body_a = first;
          pair.body_b = second;
          pair.first_ns = now;
        }
        pair.last_ns = now;
      }
    }
    if (inventory != expected_)
    {
      complete_ = false;
    }
    if (has_support)
    {
      support_seen_ = true;
      ++support_steps_;
    }
    if (now - start_ < 50000000)
    {
      return;
    }
    Frame frame;
    frame.source_id = source_;
    frame.sequence = ++sequence_;
    frame.start_ns = start_;
    frame.end_ns = now;
    frame.physics_steps = steps_;
    frame.coverage_complete = complete_ && support_seen_ && !broken_;
    frame.monitored_bodies.assign(inventory.begin(), inventory.end());
    for (const auto &body : support_)
    {
      frame.support_pairs.push_back(body + "|" + floor_);
    }
    frame.support_contact_steps = support_steps_;
    for (const auto &[key, pair] : contacts_)
    {
      (void)key;
      frame.contacts.push_back(pair);
    }
    publisher_->publish(frame);
    contacts_.clear();
    steps_ = support_steps_ = 0;
    complete_ = true;
  }

private:
  Entity model_{gz::sim::kNullEntity};
  std::map<Entity, std::string> bodies_;
  std::set<std::string> expected_, support_;
  std::string floor_, source_;
  std::shared_ptr<rclcpp::Context> context_;
  std::shared_ptr<rclcpp::Node> node_;
  rclcpp::Publisher<Frame>::SharedPtr publisher_;
  std::map<std::pair<std::string, std::string>, Pair> contacts_;
  int64_t start_{0}, last_{-1};
  uint64_t steps_{0}, support_steps_{0}, sequence_{0};
  bool complete_{true}, support_seen_{false}, broken_{false};
};
} // namespace robot_simulation

GZ_ADD_PLUGIN(robot_simulation::ContactEvidence, gz::sim::System, gz::sim::ISystemConfigure,
              gz::sim::ISystemPreUpdate, gz::sim::ISystemPostUpdate)
