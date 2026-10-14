// Demand-start LocalSystem helper: fixed firewall property + per-user app-toast policy.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using Microsoft.Win32;

class ValidClient {public ProtectionLease Lease;public string SID;}
class OverlayRaceFirewall : ServiceBase {
 internal static readonly string Root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"OverlayAppFirewall");
 static readonly string[] Games={"iRacingSim64DX11","Le Mans Ultimate","acs","acs_x86","AssettoCorsaEVO"};
 readonly ManualResetEvent stop=new ManualResetEvent(false);Thread worker;
 static string Journal {get{return Path.Combine(Root,"firewall-journal.json");}}
 static string ToastJournal {get{return Path.Combine(Root,"toasts-journal.json");}}
 static void Log(string text){try{File.AppendAllText(Path.Combine(Root,"firewall.log"),DateTimeOffset.Now.ToString("o")+" "+text+Environment.NewLine);}catch{}}
 internal static T Read<T>(string path){using(var reader=new StreamReader(new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete),Encoding.UTF8,true))using(var file=new MemoryStream(Encoding.UTF8.GetBytes(reader.ReadToEnd())))return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(file);}
 static void Write<T>(string path,T value){string temp=path+".tmp";using(var file=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None)){new DataContractJsonSerializer(typeof(T)).WriteObject(file,value);file.Flush(true);}if(File.Exists(path)){for(int attempt=0;;attempt++)try{File.Replace(temp,path,null);break;}catch(IOException error){if(attempt>=10||((error.HResult&65535)!=32&&(error.HResult&65535)!=33))throw;Thread.Sleep(20);}}else File.Move(temp,path);}
 static HashSet<string> Authorized(){return new HashSet<string>(Read<AuthorizedProfile[]>(Path.Combine(Root,"authorized-profiles.json")).Select(profile=>profile.SID),StringComparer.OrdinalIgnoreCase);}
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 static string Sid(Process process){IntPtr token;if(!OpenProcessToken(process.Handle,8,out token))return "";try{using(var id=new WindowsIdentity(token))return id.User.Value;}finally{CloseHandle(token);}}
 internal static bool Wanted(IEnumerable<ProtectionLease> clients,IEnumerable<int> gameSessions,bool toasts=false){var sessions=new HashSet<int>(gameSessions);return clients.Any(client=>client.Enabled&&(toasts?client.ToastEnabled:client.FirewallEnabled)&&sessions.Contains(client.Session));}
 static List<ValidClient> Clients(HashSet<string> authorized){
  var clients=new List<ValidClient>();
  foreach(string sid in authorized){string directory=Path.Combine(Root,"leases",sid);if(!Directory.Exists(directory))continue;
   foreach(string file in Directory.GetFiles(directory,"*.json"))try{
    if((DateTime.UtcNow-File.GetLastWriteTimeUtc(file)).TotalSeconds>5||new FileInfo(file).Length>2048)continue;
    var lease=Read<ProtectionLease>(file);using(var process=Process.GetProcessById(lease.Pid)){
     if(!process.HasExited&&process.StartTime.ToUniversalTime().Ticks==lease.Start&&process.SessionId==lease.Session&&process.ProcessName.Equals("OverlayRaceGuard",StringComparison.OrdinalIgnoreCase)&&Sid(process)==sid)clients.Add(new ValidClient{Lease=lease,SID=sid});
    }
   }catch{}
  }
  return clients;
 }
 static List<int> GameSessions(){var sessions=new List<int>();foreach(var process in Process.GetProcesses())using(process)try{if(Games.Contains(process.ProcessName,StringComparer.OrdinalIgnoreCase))sessions.Add(process.SessionId);}catch{}return sessions;}
 static void Profiles(string mode){
  string script;using(var resource=Assembly.GetExecutingAssembly().GetManifestResourceStream("FirewallProfiles"))using(var reader=new StreamReader(resource))script=reader.ReadToEnd();
  string encoded=Convert.ToBase64String(Encoding.Unicode.GetBytes("& { "+script+" } -Mode "+mode));
  string powershell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe");
  using(var process=Process.Start(new ProcessStartInfo{FileName=powershell,Arguments="-NoLogo -NoProfile -NonInteractive -EncodedCommand "+encoded,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardError=true,RedirectStandardOutput=true})){
   string error=process.StandardError.ReadToEnd(),output=process.StandardOutput.ReadToEnd();process.WaitForExit();if(process.ExitCode!=0)throw new Exception("Profiles "+mode+": "+error+output);
  }
 }
 static bool RestoreFirewall(){try{if(File.Exists(Journal))Profiles("Restore");return !File.Exists(Journal);}catch(Exception error){Log(error.Message);return false;}}
 static List<UserToastChange> ToastChanges(){return File.Exists(ToastJournal)?Read<List<UserToastChange>>(ToastJournal):new List<UserToastChange>();}
 static void SaveToasts(List<UserToastChange> changes){Write(ToastJournal,changes);}
 static bool RestoreToast(UserToastChange entry,List<UserToastChange> changes,HashSet<string> authorized){
  try{
   if(!authorized.Contains(entry.SID))throw new InvalidOperationException("Unauthorized journal SID; retained for administrator review.");
   using(var hive=Registry.Users.OpenSubKey(entry.SID,true)){
    bool restored=ToastTransaction.Restore(entry.Change,new RegistryToastBackend(hive),()=>SaveToasts(changes),Log);
    if(!restored)return false;
   }
   changes.Remove(entry);SaveToasts(changes);return true;
  }catch(Exception error){Log("TOASTS "+entry.SID+": "+error.Message);return false;}
 }
 static bool RestoreToasts(){
  try{
   if(!File.Exists(ToastJournal))return true;
   var authorized=Authorized();var changes=ToastChanges();bool complete=true;
   foreach(var entry in changes.ToArray())if(!RestoreToast(entry,changes,authorized))complete=false;
   if(changes.Count==0&&File.Exists(ToastJournal))File.Delete(ToastJournal);
   return complete;
  }catch(Exception error){Log(error.Message);return false;}
 }
 static bool Restore(){bool firewall=RestoreFirewall();bool toasts=RestoreToasts();return firewall&&toasts;}
 static Mutex Gate(){return new Mutex(false,"Global\\OverlayRaceFirewallState");}
 static bool Take(Mutex gate,int timeout){try{return gate.WaitOne(timeout);}catch(AbandonedMutexException){return true;}}
 public OverlayRaceFirewall(){ServiceName="OverlayRaceFirewall";CanStop=true;CanShutdown=true;}
 protected override void OnStart(string[] args){worker=new Thread(Loop){IsBackground=true};worker.Start();}
 protected override void OnStop(){stop.Set();if(worker!=null&&Thread.CurrentThread!=worker){RequestAdditionalTime(30000);worker.Join(28000);}}
 protected override void OnShutdown(){OnStop();}
 static void Publish(MachineStatus status){try{Write(Path.Combine(Root,"status.json"),status);File.WriteAllText(Path.Combine(Root,"status.txt"),status.Firewall);}catch(Exception error){Log("Status: "+error.Message);}}
 void Loop(){
  using(var gate=Gate()){
   if(!Take(gate,5000)){Stop();return;}
   try{
    using(var self=Process.GetCurrentProcess())using(var watchdog=Process.Start(new ProcessStartInfo{FileName=self.MainModule.FileName,Arguments="--watchdog "+self.Id+" "+self.StartTime.ToUniversalTime().Ticks,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden})){
     if(watchdog==null||watchdog.WaitForExit(100))throw new Exception("Administrator watchdog unavailable.");
     Restore();
     var authorized=Authorized();var changes=ToastChanges();var toastStates=new Dictionary<string,UserToastStatus>();var attempted=new HashSet<string>();
     var restoreRetry=new Dictionary<string,DateTime>();DateTime nextPolicyRead=DateTime.MinValue;
     var machine=new MachineStatus{Firewall="ready; waiting for game"};bool active=false;DateTime lastClient=DateTime.UtcNow;DateTime retry=DateTime.MinValue;DateTime firewallRestoreRetry=DateTime.MinValue;
     while(!stop.WaitOne(500)){
      if(watchdog.HasExited)throw new Exception("Administrator watchdog exited.");
      var clients=Clients(authorized);if(clients.Count>0)lastClient=DateTime.UtcNow;
      var games=GameSessions();bool wanted=Wanted(clients.Select(client=>client.Lease),games);
      if(wanted&&!active&&DateTime.UtcNow>=retry){
       retry=DateTime.UtcNow.AddSeconds(15);
       try{if(!RestoreFirewall())throw new Exception("Firewall restoration pending.");Profiles("Apply");active=true;machine.Firewall="NotifyOnListen=False confirmed";Log("Firewall: False confirmed in ActiveStore.");}
       catch(Exception error){Log(error.Message);machine.Firewall=RestoreFirewall()?"not applied; see log":"not applied; restoration pending";}
      }
      if(!wanted&&(active||File.Exists(Journal))&&DateTime.UtcNow>=firewallRestoreRetry){firewallRestoreRetry=DateTime.UtcNow.AddSeconds(5);if(RestoreFirewall()){active=false;machine.Firewall="ready; waiting for game";}else machine.Firewall="restoration pending";}
      machine.FirewallConfigured=active&&wanted;
      var wantedSids=new HashSet<string>(clients.Where(client=>Wanted(new[]{client.Lease},games,true)).Select(client=>client.SID));
      foreach(var sid in authorized){
       var entry=changes.FirstOrDefault(change=>change.SID==sid);
       if(!wantedSids.Contains(sid)){
        attempted.Remove(sid);
        DateTime next;bool due=!restoreRetry.TryGetValue(sid,out next)||DateTime.UtcNow>=next;
        bool restored=entry==null;
        if(entry!=null&&due){restoreRetry[sid]=DateTime.UtcNow.AddSeconds(5);restored=RestoreToast(entry,changes,authorized);}
        toastStates[sid]=new UserToastStatus{SID=sid,Status=restored?"waiting for game":"restoration pending",RestorationPending=!restored};
        continue;
       }
       if(attempted.Contains(sid))continue;
       attempted.Add(sid);
       if(entry!=null&&!RestoreToast(entry,changes,authorized)){toastStates[sid]=new UserToastStatus{SID=sid,Status="previous restoration pending",RestorationPending=true};continue;}
       entry=new UserToastChange{SID=sid,Change=new ToastChange()};changes.Add(entry);
       try{
        ToastResult result;
        using(var hive=Registry.Users.OpenSubKey(sid,true))result=ToastTransaction.Apply(entry.Change,new RegistryToastBackend(hive),()=>SaveToasts(changes),Log);
        toastStates[sid]=new UserToastStatus{SID=sid,Status=result.Status,Configured=result.Configured,RestorationPending=result.RestorationPending};
       }catch(Exception error){toastStates[sid]=new UserToastStatus{SID=sid,Status="not applied: "+error.GetType().Name};Log("TOASTS "+sid+": "+error.Message);}
       if(!entry.Change.Touched){changes.Remove(entry);SaveToasts(changes);}
      }
      if(DateTime.UtcNow>=nextPolicyRead){
       nextPolicyRead=DateTime.UtcNow.AddSeconds(5);
       foreach(string sid in wantedSids){UserToastStatus state;if(!toastStates.TryGetValue(sid,out state)||!state.Configured)continue;
        try{using(var hive=Registry.Users.OpenSubKey(sid)){var policy=new RegistryToastBackend(hive).Read();if(!policy.ValueExists||policy.Value!=1){state.Configured=false;state.Status="external change detected; policy left unchanged";}}}
        catch(Exception error){state.Configured=false;state.Status="read not confirmed: "+error.GetType().Name;}
       }
      }
      if(changes.Count==0&&File.Exists(ToastJournal))File.Delete(ToastJournal);
      machine.Toasts=toastStates.Values.ToList();machine.RestorationPending=((!active||!wanted)&&File.Exists(Journal))||machine.Toasts.Any(user=>user.RestorationPending);
      Publish(machine);
      if((DateTime.UtcNow-lastClient).TotalSeconds>20)break;
     }
    }
   }catch(Exception error){Log(error.ToString());Publish(new MachineStatus{Firewall="unavailable; see log"});}
   finally{bool restored=Restore();Publish(new MachineStatus{Firewall=restored?"inactive; values restored":"restoration pending",RestorationPending=!restored});gate.ReleaseMutex();}
  }
  Stop();
 }
 static int Watchdog(string[] args){
  int pid=Int32.Parse(args[1]);long start=Int64.Parse(args[2]);try{using(var process=Process.GetProcessById(pid)){if(process.StartTime.ToUniversalTime().Ticks==start)process.WaitForExit();}}catch(ArgumentException){}
  using(var gate=Gate()){if(!Take(gate,30000))return 1;try{for(int attempt=0;attempt<5&&!Restore();attempt++)Thread.Sleep(1000);}finally{gate.ReleaseMutex();}}
  return 0;
 }
 static void Check(bool condition,string test){if(!condition)throw new Exception(test);}
 static void SelfTest(){
  Check(!Wanted(new ProtectionLease[0],new[]{1}),"No changes without an app");
  Check(!Wanted(new[]{new ProtectionLease{Enabled=true,FirewallEnabled=true,Session=1}},new int[0]),"No changes without a game");
  Check(!Wanted(new[]{new ProtectionLease{Enabled=false,FirewallEnabled=true,ToastEnabled=true,Session=1}},new[]{1}),"Pause restores");
  Check(!Wanted(new[]{new ProtectionLease{Enabled=true,FirewallEnabled=true,Session=1}},new[]{2}),"Other session does not activate");
  Check(Wanted(new[]{new ProtectionLease{Enabled=true,FirewallEnabled=true,Session=1},new ProtectionLease{Enabled=true,FirewallEnabled=true,Session=2}},new[]{2}),"Another user retains firewall state");
  Check(Wanted(new[]{new ProtectionLease{Enabled=true,FirewallEnabled=false,ToastEnabled=true,Session=1}},new[]{1},true),"Toasts independent of firewall");
  Check(!Wanted(new[]{new ProtectionLease{Enabled=true,FirewallEnabled=false,ToastEnabled=true,Session=1}},new[]{1}),"Disabled firewall option respected");
  Check(!Wanted(new[]{new ProtectionLease{Enabled=true,ToastEnabled=false,FirewallEnabled=true,Session=1}},new[]{1},true),"Disabled toast option respected");
  Check(!Games.Contains("iRacingUI",StringComparer.OrdinalIgnoreCase),"Launcher does not activate");
  string fixture=Path.Combine(Path.GetTempPath(),"overlay-profile-bom-"+Guid.NewGuid()+".json");
  try{
   File.WriteAllText(fixture,"[{\"Name\":\"27b\",\"SID\":\"S-1-5-21-1002\",\"Profile\":\"C:\\\\Users\\\\27b\"}]",new UTF8Encoding(true));
   var profiles=Read<AuthorizedProfile[]>(fixture);
   Check(profiles.Length==1&&profiles[0].SID=="S-1-5-21-1002","Windows PowerShell UTF-8 BOM profile metadata is accepted");
  }finally{if(File.Exists(fixture))File.Delete(fixture);}
  int count=10+ToastTests.Run();
  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"firewall-tests.txt"),count+" simulated service/toast checks passed; no real write API called.");
 }
 [STAThread] static int Main(string[] args){try{if(args.Length>0){if(args[0]=="--watchdog")return Watchdog(args);if(args[0]=="--self-test"){SelfTest();return 0;}if(args[0]=="--restore"){using(var gate=Gate()){if(!Take(gate,1000))return 2;try{return Restore()?0:1;}finally{gate.ReleaseMutex();}}}return 1;}Run(new OverlayRaceFirewall());return 0;}catch(Exception error){Log(error.ToString());return 1;}}
}
