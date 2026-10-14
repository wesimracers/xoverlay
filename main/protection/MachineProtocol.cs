using System;
using System.Collections.Generic;
using System.Runtime.Serialization;

[DataContract] public class ProtectionLease {
 [DataMember] public int Pid;
 [DataMember] public long Start;
 [DataMember] public int Session;
 [DataMember] public bool Enabled;
 [DataMember] public bool FirewallEnabled;
 [DataMember] public bool ToastEnabled;
}
[DataContract] public class UserToastStatus {
 [DataMember] public string SID;
 [DataMember] public string Status;
 [DataMember] public bool Configured;
 [DataMember] public bool RestorationPending;
}
[DataContract] public class MachineStatus {
 [DataMember] public string Firewall;
 [DataMember] public bool FirewallConfigured;
 [DataMember] public bool RestorationPending;
 [DataMember] public List<UserToastStatus> Toasts=new List<UserToastStatus>();
}
[DataContract] public class UserToastChange {
 [DataMember] public string SID;
 [DataMember] public ToastChange Change;
}
[DataContract] public class AuthorizedProfile {
 [DataMember] public string Name;
 [DataMember] public string SID;
 [DataMember] public string Profile;
}
