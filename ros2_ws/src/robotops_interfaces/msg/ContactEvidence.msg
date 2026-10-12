# Read-only contact evidence for one robot; publisher uses reliable/volatile QoS.
# Windows cover (start_ns, end_ns]; silence is not evidence of no contact.
# source_id changes on adapter recreation; sequence starts at 1.
string source_id
uint64 sequence
int64 start_ns
int64 end_ns
uint64 physics_steps
bool coverage_complete
string[] monitored_bodies
string[] support_pairs
uint64 support_contact_steps
robotops_interfaces/ContactPair[] contacts
