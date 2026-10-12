# Version 1: local relay effect evidence, not downstream delivery or mission success.
uint32 schema_version
string experiment_id
string trial_id
string plan_sha256
uint64 sequence
string state
int64 ros_time_ns
uint64 clock_epoch
uint64 affected_samples
bool applied_confirmed
