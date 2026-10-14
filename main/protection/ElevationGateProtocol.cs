using System.Runtime.Serialization;

[DataContract] public class ElevationGateStatus {
 [DataMember] public string State;
 [DataMember] public bool Blocked;
 [DataMember] public bool Pending;
 [DataMember] public string Detail;
}
[DataContract] public class ElevationGateLease {
 [DataMember] public int Pid;
 [DataMember] public long Start;
 [DataMember] public int Session;
 [DataMember] public bool Enabled;
}
[DataContract] public class ElevationGateJournal {
 [DataMember] public int OriginalStart;
 [DataMember] public bool OriginalRunning;
 [DataMember] public bool Prepared;
}
