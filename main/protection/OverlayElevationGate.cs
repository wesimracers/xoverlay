// Experimental global elevation broker gate. Installation and live validation are separate.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;

public class BrokerSnapshot { public int Start; public bool Running; }
public interface BrokerBackend { BrokerSnapshot Read(); void SetStart(int value); void Stop(); void Start(); }
public static class BrokerTransaction {
 public const int Disabled=4;
 public static void Apply(BrokerBackend backend, Action<ElevationGateJournal> save) {
  var original=backend.Read();
  if(original.Start==Disabled)throw new InvalidOperationException("Appinfo was already disabled; no ownership taken.");
  if(original.Start!=2&&original.Start!=3)throw new InvalidOperationException("Unsupported Appinfo start type.");
  save(new ElevationGateJournal{OriginalStart=original.Start,OriginalRunning=original.Running,Prepared=true});
  // Stop before changing configuration, then close the trigger-restart race.
  backend.Stop();
  backend.SetStart(Disabled);
  backend.Stop();
  var applied=backend.Read();
  if(applied.Start!=Disabled||applied.Running)throw new InvalidOperationException("Appinfo gate not confirmed.");
 }
 public static void Restore(BrokerBackend backend, ElevationGateJournal journal, Action clear) {
  if(!journal.Prepared||(journal.OriginalStart!=2&&journal.OriginalStart!=3))throw new InvalidOperationException("Invalid recovery journal; administrator review required.");
  var current=backend.Read();
  if(current.Start==Disabled)backend.SetStart(journal.OriginalStart);
  else if(current.Start!=journal.OriginalStart)throw new InvalidOperationException("External Appinfo configuration preserved; recovery pending.");
  if(journal.OriginalRunning&&!backend.Read().Running)backend.Start();
  var restored=backend.Read();
  if(restored.Start!=journal.OriginalStart||(journal.OriginalRunning&&!restored.Running))throw new InvalidOperationException("Appinfo recovery not confirmed.");
  // A service started by another actor is never forcibly stopped during restoration.
  clear();
 }
}
public sealed class AppInfoBackend : BrokerBackend, IDisposable {
 const uint QueryConfig=1,ChangeConfig=2,QueryStatus=4,StartAccess=16,StopAccess=32;
 IntPtr manager,service;
 [StructLayout(LayoutKind.Sequential)] struct ServiceStatus {public uint Type,State,Accepted,Win32Exit,ServiceExit,Checkpoint,WaitHint;}
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr OpenSCManager(string machine,string database,uint access);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr OpenService(IntPtr manager,string name,uint access);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool QueryServiceConfig(IntPtr service,IntPtr config,uint size,out uint needed);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool QueryServiceStatus(IntPtr service,out ServiceStatus status);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool ChangeServiceConfig(IntPtr service,uint type,uint start,uint error,string path,string group,IntPtr tag,string dependencies,string account,string password,string display);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool ControlService(IntPtr service,uint control,out ServiceStatus status);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool StartService(IntPtr service,int count,IntPtr args);
 [DllImport("advapi32.dll")] static extern bool CloseServiceHandle(IntPtr handle);
 static Exception Error(){return new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}
 public AppInfoBackend(){
  manager=OpenSCManager(null,null,1);if(manager==IntPtr.Zero)throw Error();
  service=OpenService(manager,"Appinfo",QueryConfig|ChangeConfig|QueryStatus|StartAccess|StopAccess);
  if(service==IntPtr.Zero){var error=Error();Dispose();throw error;}
 }
 ServiceStatus Status(){ServiceStatus status;if(!QueryServiceStatus(service,out status))throw Error();return status;}
 public BrokerSnapshot Read(){
  uint needed;QueryServiceConfig(service,IntPtr.Zero,0,out needed);if(needed==0||needed>65536)throw Error();
  var buffer=Marshal.AllocHGlobal((int)needed);
  try{if(!QueryServiceConfig(service,buffer,needed,out needed))throw Error();var status=Status();
   if(status.State!=1&&status.State!=4)throw new InvalidOperationException("Appinfo is in a transitional state.");
   return new BrokerSnapshot{Start=Marshal.ReadInt32(buffer,4),Running=status.State==4};
  }finally{Marshal.FreeHGlobal(buffer);}
 }
 public void SetStart(int value){if(!ChangeServiceConfig(service,UInt32.MaxValue,(uint)value,UInt32.MaxValue,null,null,IntPtr.Zero,null,null,null,null))throw Error();}
 void Wait(uint desired){var timer=Stopwatch.StartNew();while(Status().State!=desired){if(timer.ElapsedMilliseconds>5000)throw new System.TimeoutException("Appinfo transition timed out; journal retained.");Thread.Sleep(50);}}
 public void Stop(){
  var wait=Stopwatch.StartNew();
  while(wait.ElapsedMilliseconds<8000){
   var current=Status();if(current.State==1)return;
   if(current.State==3){Wait(1);return;}
   if(current.State==2||(current.Accepted&1)==0){Thread.Sleep(100);continue;}
   ServiceStatus status;
   if(ControlService(service,1,out status)){Wait(1);return;}
   int error=Marshal.GetLastWin32Error();if(error==1062)return;
   if(error!=1061)throw new System.ComponentModel.Win32Exception(error);
   Thread.Sleep(100);
  }
  var final=Status();throw new InvalidOperationException("Appinfo stop not accepted after bounded retry; state="+final.State+"; accepted="+final.Accepted+". Original configuration will be restored.");
 }
 public void Start(){if(Status().State==4)return;if(!StartService(service,0,IntPtr.Zero)){int error=Marshal.GetLastWin32Error();if(error!=1056)throw new System.ComponentModel.Win32Exception(error);}Wait(4);}
 public void Dispose(){if(service!=IntPtr.Zero)CloseServiceHandle(service);if(manager!=IntPtr.Zero)CloseServiceHandle(manager);service=manager=IntPtr.Zero;}
}
public class OverlayElevationGate : ServiceBase {
 internal static readonly string Root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"OverlayElevationGate");
 static string Journal {get{return Path.Combine(Root,"journal.json");}}
 static string Recovery {get{return Path.Combine(Root,"recovery.flag");}}
 static string Heartbeat {get{return Path.Combine(Root,"heartbeat.json");}}
 static string WatchdogReady {get{return Path.Combine(Root,"watchdog-ready.json");}}
 readonly ManualResetEvent stopping=new ManualResetEvent(false);Thread worker;
 internal static T Read<T>(string path){using(var reader=new StreamReader(new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete),Encoding.UTF8,true))using(var buffer=new MemoryStream(Encoding.UTF8.GetBytes(reader.ReadToEnd())))return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(buffer);}
 internal static void Write<T>(string path,T value){string temporary=path+".tmp";using(var file=new FileStream(temporary,FileMode.Create,FileAccess.Write,FileShare.None)){new DataContractJsonSerializer(typeof(T)).WriteObject(file,value);file.Flush(true);}if(File.Exists(path)){for(int attempt=0;;attempt++)try{File.Replace(temporary,path,null);break;}catch(IOException error){if(attempt>=10||((error.HResult&65535)!=32&&(error.HResult&65535)!=33))throw;Thread.Sleep(20);}}else File.Move(temporary,path);}
 static void Log(string value){try{File.AppendAllText(Path.Combine(Root,"gate.log"),DateTimeOffset.Now.ToString("o")+" "+value+Environment.NewLine);}catch{}}
 static void Latch(string reason){try{File.WriteAllText(Recovery,reason);}catch(Exception error){Log("Recovery latch unavailable: "+error.Message);}}
 static Mutex Gate(){return new Mutex(false,"Global\\OverlayElevationGateState");}
 static bool Take(Mutex gate,int timeout){try{return gate.WaitOne(timeout);}catch(AbandonedMutexException){return true;}}
 static bool Restore(){
  try{if(File.Exists(Journal))using(var backend=new AppInfoBackend())BrokerTransaction.Restore(backend,Read<ElevationGateJournal>(Journal),()=>File.Delete(Journal));return !File.Exists(Journal);}
  catch(Exception error){Log("RECOVERY "+error.Message);return false;}
 }
 static void Publish(string state,bool blocked,string detail=""){
  try{Write(Path.Combine(Root,"status.json"),new ElevationGateStatus{State=state,Blocked=blocked,Pending=File.Exists(Journal)&&!blocked,Detail=detail});}catch(Exception error){Log("STATUS "+error.Message);}
 }
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr token);
 static string Sid(Process process){IntPtr token;if(!OpenProcessToken(process.Handle,8,out token))return "";try{using(var identity=new WindowsIdentity(token))return identity.User.Value;}finally{CloseHandle(token);}}
 static bool Alive(int pid,long start){try{using(var process=Process.GetProcessById(pid))return !process.HasExited&&process.StartTime.ToUniversalTime().Ticks==start;}catch{return false;}}
 static List<ElevationGateLease> Clients(){
  var clients=new List<ElevationGateLease>();
  foreach(string sid in Read<string[]>(Path.Combine(Root,"authorized-sids.json"))){
   string directory=Path.Combine(Root,"leases",sid);if(!Directory.Exists(directory))continue;
   foreach(string path in Directory.GetFiles(directory,"*.json"))try{
    if(new FileInfo(path).Length>2048||(DateTime.UtcNow-File.GetLastWriteTimeUtc(path)).TotalSeconds>5)continue;
    var lease=Read<ElevationGateLease>(path);using(var process=Process.GetProcessById(lease.Pid))
     if(!process.HasExited&&process.StartTime.ToUniversalTime().Ticks==lease.Start&&process.SessionId==lease.Session&&process.ProcessName.Equals("OverlayRaceGuard",StringComparison.OrdinalIgnoreCase)&&Sid(process)==sid)clients.Add(lease);
   }catch{}
  }
  return clients;
 }
 public OverlayElevationGate(){ServiceName="OverlayElevationGate";CanStop=true;CanShutdown=true;}
 protected override void OnStart(string[] args){worker=new Thread(Loop){IsBackground=true};worker.Start();}
 protected override void OnStop(){stopping.Set();if(worker!=null&&worker!=Thread.CurrentThread){RequestAdditionalTime(20000);worker.Join(18000);}}
 protected override void OnShutdown(){OnStop();}
 void Loop(){
  Process watchdog=null;
  bool inhibited=File.Exists(Journal)||File.Exists(Recovery);
  try{
   using(var self=Process.GetCurrentProcess()){
    // Recovery already has a SYSTEM token before the broker can be disabled.
    Write(Heartbeat,new ElevationGateLease{Pid=self.Id,Start=self.StartTime.ToUniversalTime().Ticks});
    watchdog=Process.Start(new ProcessStartInfo{FileName=self.MainModule.FileName,Arguments="--watchdog "+self.Id+" "+self.StartTime.ToUniversalTime().Ticks,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
    if(watchdog==null||watchdog.WaitForExit(100))throw new Exception("Independent recovery process unavailable.");
    var wait=Stopwatch.StartNew();bool ready=false;
    while(wait.ElapsedMilliseconds<5000&&!ready){
     if(watchdog.HasExited)throw new Exception("Independent recovery process exited during startup.");
     try{var acknowledgement=Read<ElevationGateLease>(WatchdogReady);ready=acknowledgement.Pid==self.Id&&acknowledgement.Start==self.StartTime.ToUniversalTime().Ticks;}catch{}
     if(!ready)Thread.Sleep(50);
    }
    if(!ready)throw new Exception("Independent recovery readiness was not confirmed; broker unchanged.");
   }
   using(var gate=Gate()){
    if(!Take(gate,15000))throw new Exception("Recovery lock unavailable.");
    try{if(File.Exists(Journal)){Latch("startup recovery");Restore();}}finally{gate.ReleaseMutex();}
   }
   bool attempted=false;
   while(!stopping.WaitOne(500)){
    if(watchdog.HasExited)throw new Exception("Independent recovery process exited.");
    using(var self=Process.GetCurrentProcess())Write(Heartbeat,new ElevationGateLease{Pid=self.Id,Start=self.StartTime.ToUniversalTime().Ticks});
    var clients=Clients();bool wanted=clients.Any(client=>client.Enabled);
    using(var gate=Gate()){
     if(!Take(gate,15000))throw new Exception("Recovery lock unavailable.");
     try{
      if(!wanted){
       bool restored=Restore();bool latched=File.Exists(Recovery);
       Publish(!restored?"recovery pending":latched?"not active; recovery latch; retry administrative setup after Windows recovery":"ready; app closed or game mode disabled",false);
       if(restored){attempted=false;inhibited=latched;}continue;
      }
      if(inhibited||File.Exists(Recovery)){Restore();Publish("not active; recovery latch; retry administrative setup after Windows recovery",false);continue;}
      if(!attempted){
       attempted=true;
       try{using(var backend=new AppInfoBackend())BrokerTransaction.Apply(backend,journal=>Write(Journal,journal));Log("APPINFO disabled and stopped; global interactive elevation gate active.");}
       catch(Exception error){Log("ACTIVATION "+error.ToString());inhibited=true;Latch("activation failed");Restore();Publish("activation failed; administrative recovery required before retrying",false,"Windows rejected activation; see protected helper log.");continue;}
      }
      if(!File.Exists(Journal)){inhibited=true;Latch("journal missing");Publish("not active; recovery journal missing",false);continue;}
      try{using(var backend=new AppInfoBackend()){var broker=backend.Read();if(broker.Start!=BrokerTransaction.Disabled||broker.Running)throw new Exception("Broker state changed externally.");}Publish("interactive elevation broker blocked globally; application error dialogs remain possible",true);}
      catch(Exception error){inhibited=true;Latch("verification failed");Restore();Publish("verification failed; recovery requested",false,error.Message);}
     }finally{gate.ReleaseMutex();}
    }
   }
  }catch(Exception error){Log("SERVICE "+error);}
  finally{
   using(var gate=Gate())if(Take(gate,15000))try{if(File.Exists(Journal))Latch("service exit");bool restored=Restore();Publish(restored?"inactive; Appinfo restored":"recovery pending",false);}finally{gate.ReleaseMutex();}
   if(watchdog!=null)watchdog.Dispose();
  }
  // A failed service worker must terminate so SCM failure recovery can restart it.
  if(!stopping.WaitOne(0))Environment.Exit(1);
 }
 static int Watchdog(string[] args){
  int pid=Int32.Parse(args[1]);long start=Int64.Parse(args[2]);
  if(!Alive(pid,start))return 1;
  Write(WatchdogReady,new ElevationGateLease{Pid=pid,Start=start});
  DateTime unhealthySince=DateTime.MinValue;
  while(true){
   bool alive=Alive(pid,start);bool healthy=false;
   try{var heartbeat=Read<ElevationGateLease>(Heartbeat);healthy=heartbeat.Pid==pid&&heartbeat.Start==start&&(DateTime.UtcNow-File.GetLastWriteTimeUtc(Heartbeat)).TotalSeconds<15;}catch{}
   if(!alive||!healthy){
    if(unhealthySince==DateTime.MinValue)unhealthySince=DateTime.UtcNow;
    using(var gate=Gate()){
     if(!Take(gate,1000)){
      // Only terminate our dedicated helper if a hung service holds the recovery lock.
      // Never terminate Appinfo's shared svchost, OverlayApp, or a game process.
      if(alive&&(DateTime.UtcNow-unhealthySince).TotalSeconds>15)try{
       using(var process=Process.GetProcessById(pid))using(var self=Process.GetCurrentProcess())
        if(process.StartTime.ToUniversalTime().Ticks==start&&process.ProcessName=="OverlayElevationGate"&&Sid(process)=="S-1-5-18"&&String.Equals(process.MainModule.FileName,self.MainModule.FileName,StringComparison.OrdinalIgnoreCase)){Log("WATCHDOG terminating hung dedicated gate helper to release recovery lock.");process.Kill();}
      }catch(Exception error){Log("WATCHDOG hung helper: "+error.Message);}
      continue;
     }
     try{
     // Recheck after acquiring the lock; never undo another healthy service instance.
     try{var heartbeat=Read<ElevationGateLease>(Heartbeat);if((heartbeat.Pid!=pid||heartbeat.Start!=start)&&Alive(heartbeat.Pid,heartbeat.Start))return 0;
      healthy=Alive(pid,start)&&heartbeat.Pid==pid&&heartbeat.Start==start&&(DateTime.UtcNow-File.GetLastWriteTimeUtc(Heartbeat)).TotalSeconds<15;}catch{healthy=false;}
     if(!healthy){if(File.Exists(Journal))Latch("watchdog recovery");bool restored=Restore();Publish(restored?"watchdog restored Appinfo":"watchdog recovery pending",false);if(restored&&!Alive(pid,start))return 0;}
     }finally{gate.ReleaseMutex();}
    }
   }else unhealthySince=DateTime.MinValue;
   Thread.Sleep(1000);
  }
 }
 static int Main(string[] args){
  if(args.Length==1&&args[0]=="--self-test"){BrokerTests.Run();return 0;}
  if(args.Length==3&&args[0]=="--watchdog"&&WindowsIdentity.GetCurrent().IsSystem)return Watchdog(args);
  if(args.Length!=0||!WindowsIdentity.GetCurrent().IsSystem)return 2;
  ServiceBase.Run(new OverlayElevationGate());return 0;
 }
}
public class FakeBroker : BrokerBackend {
 public int StartType=3;public bool Running=true;public bool FailDisable,FailStop,FailStart,FailRestore,IgnoreDisable,RestartOnDisable;
 public List<string> Calls=new List<string>();
 public BrokerSnapshot Read(){return new BrokerSnapshot{Start=StartType,Running=Running};}
 public void SetStart(int value){Calls.Add("config:"+value);if(value==4&&FailDisable||value!=4&&FailRestore)throw new Exception("simulated configuration failure");if(!IgnoreDisable)StartType=value;if(value==4&&RestartOnDisable)Running=true;}
 public void Stop(){Calls.Add("stop");if(FailStop)throw new Exception("simulated stop failure");Running=false;}
 public void Start(){Calls.Add("start");if(FailStart)throw new Exception("simulated start failure");Running=true;}
}
public static class BrokerTests {
 static int count;static void Check(bool value,string test){if(!value)throw new Exception("TEST FAILED: "+test);count++;}
 static bool Fails(Action action){try{action();return false;}catch{return true;}}
 public static void Run(){
  foreach(int start in new[]{2,3})foreach(bool running in new[]{false,true}){
   var backend=new FakeBroker{StartType=start,Running=running};ElevationGateJournal journal=null;
   BrokerTransaction.Apply(backend,snapshot=>{Check(backend.Calls.Count==0,"durable journal precedes every service mutation");journal=snapshot;});
   Check(backend.StartType==4&&!backend.Running,"disabled and stopped required");
   BrokerTransaction.Restore(backend,journal,()=>journal=null);Check(journal==null&&backend.StartType==start&&backend.Running==running,"restore exact original config and running state");
  }
  var b=new FakeBroker();Check(Fails(()=>BrokerTransaction.Apply(b,j=>{throw new IOException("disk full");}))&&b.Calls.Count==0,"journal failure leaves broker unchanged");
  b=new FakeBroker{RestartOnDisable=true};BrokerTransaction.Apply(b,j=>{});Check(!b.Running&&b.Calls.SequenceEqual(new[]{"stop","config:4","stop"}),"stop before configuration and stop again closes trigger restart race");
  foreach(string failure in new[]{"disable","stop"}){
   b=new FakeBroker{FailDisable=failure=="disable",FailStop=failure=="stop"};ElevationGateJournal j=null;
   Check(Fails(()=>BrokerTransaction.Apply(b,value=>j=value))&&j!=null,"partial activation failure is recoverable");
   BrokerTransaction.Restore(b,j,()=>j=null);Check(j==null&&b.StartType==3&&b.Running,"rollback partial activation");
  }
  foreach(bool originallyRunning in new[]{true,false}){
   b=new FakeBroker{StartType=4,Running=false};var j=new ElevationGateJournal{OriginalStart=3,OriginalRunning=originallyRunning,Prepared=true};
   BrokerTransaction.Restore(b,j,()=>j=null);Check(j==null&&b.StartType==3&&b.Running==originallyRunning,"fresh recovery instance restores crash snapshot");
  }
  b=new FakeBroker{StartType=3,Running=false};var journalAfterConfig=new ElevationGateJournal{OriginalStart=3,OriginalRunning=true,Prepared=true};
  BrokerTransaction.Restore(b,journalAfterConfig,()=>journalAfterConfig=null);Check(b.Running&&journalAfterConfig==null,"retry after crash during recovery");
  b=new FakeBroker{StartType=4,Running=false,FailRestore=true};var retained=new ElevationGateJournal{OriginalStart=3,OriginalRunning=true,Prepared=true};
  Check(Fails(()=>BrokerTransaction.Restore(b,retained,()=>retained=null))&&retained!=null,"failed config recovery retains journal");
  b.FailRestore=false;b.FailStart=true;Check(Fails(()=>BrokerTransaction.Restore(b,retained,()=>retained=null))&&retained!=null&&b.StartType==3,"failed start recovery retains journal after restoring config");
  b.FailStart=false;BrokerTransaction.Restore(b,retained,()=>retained=null);Check(retained==null&&b.Running,"recovery retry completes");
  b=new FakeBroker{StartType=2,Running=true};retained=new ElevationGateJournal{OriginalStart=3,Prepared=true};
  Check(Fails(()=>BrokerTransaction.Restore(b,retained,()=>retained=null))&&retained!=null&&b.Calls.Count==0,"external config preserved");
  b=new FakeBroker{StartType=4};Check(Fails(()=>BrokerTransaction.Apply(b,j=>{}))&&b.Calls.Count==0,"preexisting disabled broker not claimed");
  b=new FakeBroker{IgnoreDisable=true};Check(Fails(()=>BrokerTransaction.Apply(b,j=>{})),"unconfirmed disable cannot report success");
  b=new FakeBroker{StartType=3,Running=true};retained=new ElevationGateJournal{OriginalStart=3,OriginalRunning=false,Prepared=true};BrokerTransaction.Restore(b,retained,()=>retained=null);Check(b.Running&&b.Calls.Count==0,"externally started broker preserved");
  b=new FakeBroker();Check(Fails(()=>BrokerTransaction.Restore(b,new ElevationGateJournal{OriginalStart=4,Prepared=true},()=>{}))&&b.Calls.Count==0,"corrupt snapshot refused");
  b=new FakeBroker{StartType=4,Running=false};retained=new ElevationGateJournal{OriginalStart=3,OriginalRunning=true,Prepared=true};
  Check(Fails(()=>BrokerTransaction.Restore(b,retained,()=>{throw new IOException("journal clear failed");}))&&retained!=null&&b.StartType==3&&b.Running,"clear failure retains retryable journal after successful restoration");
  string statusPath=Path.Combine(Path.GetTempPath(),"gate-reader-test-"+Guid.NewGuid()+".json");
  try{
   OverlayElevationGate.Write(statusPath,new ElevationGateStatus{State="before"});
   var reader=new FileStream(statusPath,FileMode.Open,FileAccess.Read,FileShare.Read);
   var release=new Thread(()=>{Thread.Sleep(80);reader.Dispose();});release.Start();
   OverlayElevationGate.Write(statusPath,new ElevationGateStatus{State="after"});release.Join();
   Check(OverlayElevationGate.Read<ElevationGateStatus>(statusPath).State=="after","atomic status write survives a transient non-delete-sharing reader");
  }finally{if(File.Exists(statusPath))File.Delete(statusPath);}
  Console.WriteLine(count+" isolated broker transaction tests passed; no service or registry API was called.");
  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"gate-tests.txt"),count+" isolated tests passed. No live Windows gate was activated.");
 }
}
