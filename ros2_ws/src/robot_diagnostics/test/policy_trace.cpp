// Test-only stdin trace runner: the Python offline policy is the independent oracle.
#include <iostream>
#include "robot_diagnostics/freshness.hpp"
int main()
{
  robot_diagnostics::Monitor monitor({"odom", "scan", "imu"});
  std::string action, stream;
  int64_t stamp, now;
  double steady;
  while (std::cin >> action) {
    if (action == "reset") {monitor.reset_clock(); continue;}
    if (action == "observe") {
      std::cin >> stream >> stamp >> now >> steady;
      monitor.observe(stream, stamp, now, steady);
    } else {
      std::cin >> now >> steady;
      for (const auto & [name, status] : monitor.evaluate(now, steady)) {
        std::cout << name << ' ' << int(status.level) << ' ' << status.reason;
        for (const auto & [key, value] : status.values) {std::cout << ' ' << key << '=' << value;}
        std::cout << '\n';
      }
    }
  }
}
