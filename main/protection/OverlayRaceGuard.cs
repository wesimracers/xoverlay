// .NET Framework 4.x / Windows 10-11. No injection; input observers always forward.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[DataContract] public class Config {
 [DataMember] public bool MuteAppToasts;
 [DataMember] public bool ExtendForegroundTimeout;
 [DataMember] public bool GeneralWindowGuard;
 [DataMember] public bool SuppressFirewallPrompt;
 [DataMember] public bool BlockInteractiveElevation;
 [DataMember] public string AlertMonitor;
 [DataMember] public bool RouteAlways;
 [DataMember] public int UserInputGraceMs;
 [DataMember] public string[] Games;
 [DataMember] public string[] KeepVisible;
 [DataMember] public string[] AllowedProcessNames;
 [DataMember] public string[] AllowedExecutablePaths;
 [DataMember] public Rule[] ExactRules;
 public void Validate() {
  if(Games==null || Games.Length==0 || Games.Any(x=>String.IsNullOrWhiteSpace(x))) throw new Exception("Invalid Games configuration.");
  if(UserInputGraceMs<2000 || UserInputGraceMs>15000) throw new Exception("UserInputGraceMs must be between 2000 and 15000.");
  KeepVisible=KeepVisible??new string[0]; ExactRules=ExactRules??new Rule[0];
  AllowedProcessNames=AllowedProcessNames??new string[0];AllowedExecutablePaths=AllowedExecutablePaths??new string[0];
  if(AllowedExecutablePaths.Any(path=>String.IsNullOrWhiteSpace(path)||!System.IO.Path.IsPathRooted(path)))throw new Exception("Allowed executable paths must be absolute.");
  foreach(var r in ExactRules) if(r.Enabled && (String.IsNullOrWhiteSpace(r.Path)||!System.IO.Path.IsPathRooted(r.Path)||String.IsNullOrWhiteSpace(r.Title)||String.IsNullOrWhiteSpace(r.Class))) throw new Exception("A rule requires an absolute Path and exact Title and Class.");
 }
}
[DataContract] public class Rule { [DataMember] public bool Enabled; [DataMember] public string Path; [DataMember] public string Title; [DataMember] public string Class; }
[DataContract] public class Hidden {
 [DataMember] public long Handle;
 [DataMember] public int Pid;
 [DataMember] public long Start;
 [DataMember] public string Class;
 [DataMember] public string Path;
 [DataMember] public string Title;
 [DataMember] public bool RestoreQueued;
 [DataMember] public bool Moved;
 [DataMember] public string Monitor;
 [DataMember] public string OriginalMonitor;
 [DataMember] public int Left; [DataMember] public int Top; [DataMember] public int Width; [DataMember] public int Height;
}
[DataContract] public class Journal {
 [DataMember] public int OwnerPid;
 [DataMember] public long OwnerStart;
 [DataMember] public bool PolicyTouched;
 [DataMember] public bool PolicyExisted;
 [DataMember] public int PolicyOriginal;
 [DataMember] public bool PolicyKeyExisted;
 [DataMember] public bool FocusTouched;
 [DataMember] public uint FocusOriginal;
 [DataMember] public List<Hidden> Windows = new List<Hidden>();
 public bool Pending { get {return PolicyTouched||FocusTouched||Windows.Count>0;} }
}
public class WindowInfo {
 public long Handle; public int Pid; public long Start; public string Name=""; public string Path=""; public string Title=""; public string Class="";
 public bool Visible; public bool Minimized; public bool Topmost; public bool Owned; public bool PassThrough;
}
public static class Native {
 public delegate bool EnumProc(IntPtr h,IntPtr l);
 public delegate void EventProc(IntPtr hook,uint ev,IntPtr h,int obj,int child,uint thread,uint time);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb,IntPtr l);
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint flags);
 [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h,uint cmd);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",EntryPoint="GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr h,int index);
 [DllImport("user32.dll",SetLastError=true)] public static extern bool ShowWindowAsync(IntPtr h,int cmd);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll",SetLastError=true)] public static extern IntPtr SetWinEventHook(uint min,uint max,IntPtr mod,EventProc cb,uint pid,uint thread,uint flags);
 [DllImport("user32.dll")] public static extern bool UnhookWinEvent(IntPtr hook);
 [DllImport("user32.dll")] static extern short GetAsyncKeyState(int vk);
 [StructLayout(LayoutKind.Sequential)] struct LastInput {public uint size; public uint time;}
 [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LastInput li);
 [DllImport("user32.dll",EntryPoint="SystemParametersInfoW",SetLastError=true)] static extern bool SpiGet(uint action,uint param,ref uint value,uint flags);
 [DllImport("user32.dll",EntryPoint="SystemParametersInfoW",SetLastError=true)] static extern bool SpiSet(uint action,uint param,IntPtr value,uint flags);
 [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool QueryFullProcessImageName(IntPtr h,uint flags,StringBuilder path,ref int size);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
 public static uint GetFocusTimeout() {uint v=0;if(!SpiGet(0x2000,0,ref v,0)) throw new System.ComponentModel.Win32Exception();return v;}
 // pvParam is the numeric value, NOT a pointer. flags=0: never persist in the user profile.
 public static void SetFocusTimeout(uint v) {if(!SpiSet(0x2001,0,new IntPtr((long)v),0)) throw new System.ComponentModel.Win32Exception();}
 public static uint InputAge() {var li=new LastInput{size=8};if(!GetLastInputInfo(ref li)) return 0;return unchecked((uint)Environment.TickCount-li.time);}
 public static bool SwitchingKeys() {return new[]{0x12,0x09,0x5b,0x5c,0x11,0x01,0x02}.Any(k=>(GetAsyncKeyState(k)&0x8000)!=0);}
 public static bool SwitchingShortcuts(){return new[]{0x12,0x09,0x5b,0x5c,0x11,0x1b}.Any(k=>(GetAsyncKeyState(k)&0x8000)!=0);}
 public static WindowInfo Info(IntPtr h) {
  var w=new WindowInfo{Handle=h.ToInt64(),Visible=IsWindowVisible(h),Minimized=IsIconic(h)};
  uint pid;GetWindowThreadProcessId(h,out pid);w.Pid=(int)pid;
  var t=new StringBuilder(1024);GetWindowText(h,t,t.Capacity);w.Title=t.ToString();
  t=new StringBuilder(256);GetClassName(h,t,t.Capacity);w.Class=t.ToString();
  long style=GetWindowLongPtr(h,-20).ToInt64();w.Topmost=(style&8)!=0;w.PassThrough=(style&0x08000020)!=0;w.Owned=GetWindow(h,4)!=IntPtr.Zero;
  try {using(var p=Process.GetProcessById(w.Pid)){w.Name=p.ProcessName;w.Start=p.StartTime.ToUniversalTime().Ticks;}} catch{}
  var ph=OpenProcess(0x1000,false,pid);
  if(ph!=IntPtr.Zero) {try {t=new StringBuilder(32768);int n=t.Capacity;if(QueryFullProcessImageName(ph,0,t,ref n))w.Path=t.ToString();} finally{CloseHandle(ph);}}
  return w;
 }
 public static List<WindowInfo> Windows() {var list=new List<WindowInfo>();EnumWindows((h,l)=>{if(IsWindowVisible(h))list.Add(Info(h));return true;},IntPtr.Zero);return list;}
}
public interface SettingsBackend {
 ToastBackend Toasts {get;}
 uint ReadFocus(); void WriteFocus(uint value);
}
public class WindowsBackend : SettingsBackend {
 public ToastBackend Toasts {get{return new RegistryToastBackend(Registry.CurrentUser);}}
 public uint ReadFocus(){return Native.GetFocusTimeout();} public void WriteFocus(uint v){Native.SetFocusTimeout(v);}
}
public class SettingsState {
 public ToastResult Toasts=new ToastResult();public string Focus="waiting for game";
 public bool FocusConfigured;public bool RestorationPending;
}
public class WindowPlan {public bool Suppress;public bool Route;public bool ReturnFocus;}
public static class Settings {
 public const uint Target=86400000; // 24 hours, finite, current session only.
 static ToastChange PolicyChange(Journal j){return new ToastChange{Touched=j.PolicyTouched,Original=new ToastSnapshot{KeyExists=j.PolicyKeyExisted,ValueExists=j.PolicyExisted,Value=j.PolicyOriginal}};}
 static void CopyPolicy(Journal j,ToastChange change){j.PolicyTouched=change.Touched;if(change.Original!=null){j.PolicyKeyExisted=change.Original.KeyExists;j.PolicyExisted=change.Original.ValueExists;j.PolicyOriginal=change.Original.Value;}}
 public static SettingsState Apply(Journal j,Config c,SettingsBackend b,Action save,Action<string> log,bool delegatedToasts=false,bool deniedToasts=false) {
  var state=new SettingsState();
  if(!c.MuteAppToasts)state.Toasts.Status="off";
  else if(delegatedToasts)state.Toasts.Status="waiting for administrator helper";
  else if(deniedToasts){state.Toasts.Status="not applied: access denied; install administrator helper";state.Toasts.AccessDenied=true;}
  else{
   var change=PolicyChange(j);
   state.Toasts=ToastTransaction.Apply(change,b.Toasts,()=>{CopyPolicy(j,change);save();},log);
   CopyPolicy(j,change);state.RestorationPending=state.Toasts.RestorationPending;
  }
  if(!c.ExtendForegroundTimeout)state.Focus="off";
  else try{
   j.FocusOriginal=b.ReadFocus();
   if(j.FocusOriginal>=Target){state.Focus="already configured";state.FocusConfigured=true;}
   else{
    j.FocusTouched=true;save();b.WriteFocus(Target);if(b.ReadFocus()!=Target)throw new Exception("Value not confirmed.");
    state.Focus="configuration applied";state.FocusConfigured=true;log("FOCUS temporary timeout applied.");
   }
  }catch(Exception error){
   state.Focus="not applied: "+error.GetType().Name;
   if(j.FocusTouched&&!RestoreFocus(j,b,save,log))state.RestorationPending=true;
   log("FOCUS WARNING: "+error.Message);
  }
  return state;
 }
 static bool RestoreFocus(Journal j,SettingsBackend b,Action save,Action<string> log){
  if(!j.FocusTouched)return true;
  try{uint current=b.ReadFocus();if(current==Target){b.WriteFocus(j.FocusOriginal);if(b.ReadFocus()!=j.FocusOriginal)throw new Exception("Restoration not confirmed.");}else if(current!=j.FocusOriginal)log("FOCUS external change preserved.");j.FocusTouched=false;save();return true;}catch(Exception error){log("FOCUS RESTORE ERROR: "+error.Message);return false;}
 }
 public static bool Restore(Journal j,SettingsBackend b,Action save,Action<string> log) {
  var change=PolicyChange(j);bool policy=ToastTransaction.Restore(change,b.Toasts,()=>{CopyPolicy(j,change);save();},log);CopyPolicy(j,change);
  bool focus=RestoreFocus(j,b,save,log);return policy&&focus;
 }
}
public static class Guard {
 public static int Session=Process.GetCurrentProcess().SessionId;
 public static string Root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OverlayApp","RaceProtection","Session-"+Session);
 public static string StateFile {get{return Path.Combine(Root,"estado.json");}}
 public static string StopFile {get{return Path.Combine(Root,"parar.flag");}}
 public static string MutexName="Local\\OverlayRaceProtection-"+WindowsIdentity.GetCurrent().User.Value;
 public static string PauseFile {get{return Path.Combine(Root,"pausar.flag");}}
 public static string ConfigFile=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"config.json");
 public static bool HasOwners() {
  bool alive=false;
  foreach(string f in Directory.GetFiles(Root,"owner-*.json"))try{var o=Read<Owner>(f);if(Alive(o.Pid,o.Start))alive=true;else File.Delete(f);}catch{try{File.Delete(f);}catch{}}
  return alive;
 }
 public static void Log(string s){
  // Logging must never prevent restoration, including disk full/access errors.
  try{using(var gate=new Mutex(false,MutexName+"-Log")){bool taken=false;try{try{taken=gate.WaitOne(1000);}catch(AbandonedMutexException){taken=true;}if(taken){Directory.CreateDirectory(Root);var f=Path.Combine(Root,"registro-"+DateTime.Now.ToString("yyyy-MM-dd")+".log");File.AppendAllText(f,DateTimeOffset.Now.ToString("o")+" "+s.Replace('\r',' ').Replace('\n',' ')+Environment.NewLine,Encoding.UTF8);}}finally{if(taken)gate.ReleaseMutex();}}}catch(Exception e){Debug.WriteLine("Log unavailable: "+e.Message);}
 }
 public static T Read<T>(string p){using(var f=new FileStream(p,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(f);}
 public static void Write<T>(string p,T value){var temp=p+".tmp";using(var f=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None)){new DataContractJsonSerializer(typeof(T)).WriteObject(f,value);f.Flush(true);}if(File.Exists(p)){for(int attempt=0;;attempt++)try{File.Replace(temp,p,null);break;}catch(IOException error){if(attempt>=10||((error.HResult&65535)!=32&&(error.HResult&65535)!=33))throw;Thread.Sleep(20);}}else File.Move(temp,p);}
 public static bool Contains(string[] a,string s){return a.Any(x=>String.Equals(x,s,StringComparison.OrdinalIgnoreCase));}
 public static bool Game(Config c,WindowInfo w){return Contains(c.Games,w.Name);}
 public static bool ConsoleWindow(WindowInfo w) {
  return (w.Class=="ConsoleWindowClass"||w.Class=="CASCADIA_HOSTING_WINDOW_CLASS")&&new[]{"conhost","OpenConsole","WindowsTerminal","powershell","pwsh","cmd"}.Any(n=>String.Equals(n,w.Name,StringComparison.OrdinalIgnoreCase));
 }
 public static bool SafeCandidate(Config c,WindowInfo w) {
  if((c.AllowedProcessNames??new string[0]).Any(name=>String.Equals(name,w.Name,StringComparison.OrdinalIgnoreCase))||(c.AllowedExecutablePaths??new string[0]).Any(path=>String.Equals(path,w.Path,StringComparison.OrdinalIgnoreCase)))return false;
  if(!w.Visible||w.Minimized||w.PassThrough||w.Pid==Process.GetCurrentProcess().Id||w.Start==0||String.IsNullOrEmpty(w.Path))return false;
  if(Game(c,w)||Contains(c.KeepVisible,w.Name))return false;
  // Hard exclusions cannot be removed by configuration. Includes security / anti-cheat / peripherals / existing overlays.
  if(new[]{"consent","CredentialUIBroker","SecurityHealthSystray","SecHealthUI","TextInputHost","Taskmgr","WerFault","WerFaultSecure","BsSndRpt64","EasyAntiCheat_EOS","EasyAntiCheat","ChatGPT","OverlayApp","OverlayRaceGuard","sc-tuner","iRacingUI","iRacingLauncher64","AssettoCorsa","acShowroom","Launch Le Mans Ultimate","start_protected_game","JoyToKey","XMouseButtonControl","voicemeeter_x64","bk-connect","pulsoid-desktop","GameOverlayUI","NVIDIA Overlay","RTSS","RTSSHooksLoader64","SimHubWPF","CrewChiefV4","Discord"}.Any(n=>String.Equals(n,w.Name,StringComparison.OrdinalIgnoreCase)))return false;
  if(new[]{"Shell_TrayWnd","Shell_SecondaryTrayWnd","Progman","WorkerW"}.Contains(w.Class))return false;
  if(w.Name.IndexOf("anticheat",StringComparison.OrdinalIgnoreCase)>=0||w.Name.IndexOf("defender",StringComparison.OrdinalIgnoreCase)>=0)return false;
  return true;
 }
 public static bool Decide(bool general,bool exact,bool fresh,bool stole,bool popup,bool gameForeground,uint age,int grace,bool keys,bool safe){return safe&&!keys&&age>=grace&&((general&&(stole||(fresh&&popup&&gameForeground)))||(exact&&gameForeground));}
 public static bool FreshEligible(uint intentAge,int grace){return intentAge>=grace;}
 public static WindowPlan Plan(bool active,bool general,bool routeAlways,bool destination,bool gameForeground,bool fresh,bool stole,bool popup,bool safe,uint age,int grace,bool keys,bool exact=false,bool strictDuringGame=false){
  // Broker failures can be ordinary dialogs created during driving input.
  if(active&&strictDuringGame&&(gameForeground||stole)&&popup&&!keys)age=(uint)grace;
  bool suppress=Decide(active&&general,active&&exact,fresh,stole,popup,gameForeground,age,grace,keys,safe);
  bool route=destination&&(suppress||(routeAlways&&fresh&&popup&&safe&&!keys&&age>=grace));
  return new WindowPlan{Suppress=suppress,Route=route,ReturnFocus=suppress&&stole};
 }
 public static bool Alive(int id,long start){try{using(var p=Process.GetProcessById(id))return !p.HasExited&&p.StartTime.ToUniversalTime().Ticks==start;}catch{return false;}}
 public static void RestoreWindows(Journal j,Action save,Func<Hidden,bool> filter=null) {
  foreach(var w in j.Windows.Where(window=>filter==null||filter(window)).ToArray())try {
   var h=new IntPtr(w.Handle);var current=Native.Info(h);
   if(Native.IsWindow(h)&&current.Pid==w.Pid&&current.Start==w.Start&&current.Class==w.Class&&String.Equals(current.Path,w.Path,StringComparison.OrdinalIgnoreCase)) {
    w.RestoreQueued=true;save();
    if(w.Moved){if(!WindowRouting.Restore(h,w))throw new Exception("Original position not yet restored.");}
    else if(!current.Visible){
    if(!Native.ShowWindowAsync(h,8))throw new Exception("SW_SHOWNA was not queued.");
    w.RestoreQueued=true;save();Thread.Sleep(50);
    if(!Native.IsWindowVisible(h))throw new Exception("Restoration not yet confirmed; journal retained.");
    Log("WINDOW restored without activation: "+w.Path+" | "+w.Title);
    }
   }
   j.Windows.Remove(w);save();
  }catch(Exception e){Log("WINDOW RESTORE ERROR: "+e.Message);}
 }
 public static bool Restore(Journal j) {Action save=()=>Write(StateFile,j);RestoreWindows(j,save);Settings.Restore(j,new WindowsBackend(),save,Log);if(!j.Pending&&File.Exists(StateFile))File.Delete(StateFile);return !j.Pending;}
 [STAThread] public static int Main(string[] args) {
  try {
   string mode=args.Length>0?args[0]:"--diagnose";
   if(mode=="--self-test"){Tests.Run();return 0;}
   if(mode=="--diagnose"){Diagnose();return 0;}
   Directory.CreateDirectory(Root);
   if(mode=="--run") {
    int index=Array.IndexOf(args,"--owner");if(index<0||index+1>=args.Length)throw new Exception("Protection must be started by OverlayApp.");
    using(var p=Process.GetProcessById(Int32.Parse(args[index+1]))) {
     if(p.SessionId!=Session||!(p.ProcessName.Equals("OverlayApp",StringComparison.OrdinalIgnoreCase)||p.ProcessName.StartsWith("python",StringComparison.OrdinalIgnoreCase)))throw new Exception("Invalid owner.");
     Write(Path.Combine(Root,"owner-"+p.Id+".json"),new Owner{Pid=p.Id,Start=p.StartTime.ToUniversalTime().Ticks});
    }
   }
   if(mode=="--stop") {File.WriteAllText(StopFile,"stop");Log("STOP requested.");return 0;}
   if(mode=="--watchdog") {
    int id=Int32.Parse(args[1]);long start=Int64.Parse(args[2]);
    try{using(var p=Process.GetProcessById(id)){if(p.StartTime.ToUniversalTime().Ticks==start)p.WaitForExit();}}catch(ArgumentException){}
    using(var gate=new Mutex(false,MutexName)){bool taken=false;try{try{taken=gate.WaitOne(3000);}catch(AbandonedMutexException){taken=true;}if(taken&&File.Exists(StateFile)){var j=Read<Journal>(StateFile);if(j.OwnerPid==id&&j.OwnerStart==start){Log("WATCHDOG process ended; restoring.");for(int attempt=0;attempt<5&&!Restore(j);attempt++)Thread.Sleep(100);}}}finally{if(taken)gate.ReleaseMutex();}}
    return 0;
   }
   if(mode!="--run"&&mode!="--restore")throw new Exception("Unknown mode.");
   using(var gate=new Mutex(false,MutexName)) {
    bool taken=false;try {
     try{taken=gate.WaitOne(mode=="--run"?3000:0);}catch(AbandonedMutexException){taken=true;}
     if(!taken)return 0; // The existing guard now owns the additional app lease.
     if(File.Exists(StateFile)&&!Restore(Read<Journal>(StateFile)))throw new Exception("Restoration pending. See the log and close the games before retrying recovery.");
     if(mode=="--restore"){using(var recovery=new FirewallClient())recovery.Refresh(false);Log("Local RESTORE completed; firewall recovery requested if installed.");return 0;}
     if(File.Exists(StopFile))File.Delete(StopFile);
     int ci=Array.IndexOf(args,"--config");if(ci>=0&&ci+1<args.Length)ConfigFile=args[ci+1];
     var c=Read<Config>(ConfigFile);c.Validate();
     Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
     using(var context=new GuardContext(c))Application.Run(context);
    }finally{if(taken)gate.ReleaseMutex();}
   }
   return 0;
  }catch(Exception e){Log("ERROR: "+e);if(args.Length>0&&args[0]=="--self-test")Console.Error.WriteLine(e);return 1;}
 }
 static void Diagnose() {
  var c=Read<Config>(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"config.json"));c.Validate();
  var companion=new[]{"garage61-agent","garage61-launcher","VrsOne","CloudXrService","OverlayApp","sc-tuner","JoyToKey","Trading Paints"};
  var report=new StringBuilder();report.AppendLine("READ-ONLY DIAGNOSTICS - "+DateTimeOffset.Now.ToString("o"));
  report.AppendLine("UAC="+GuardStatus.UacCoverage+"; initial consent does not block later requests.");
  report.AppendLine("ForegroundLockTimeout="+Native.GetFocusTimeout());
  foreach(var p in Process.GetProcesses())using(p){try{if(Contains(c.Games,p.ProcessName)||Contains(companion,p.ProcessName))report.AppendLine("PROCESS "+p.ProcessName+" pid="+p.Id);}catch{}}
  long fg=Native.GetForegroundWindow().ToInt64();
  foreach(var w in Native.Windows())if(Game(c,w)||Contains(companion,w.Name)||w.Class=="#32770")report.AppendLine((w.Handle==fg?"FOCUS ":"WINDOW ")+w.Name+" pid="+w.Pid+" class="+w.Class+" title="+w.Title+" path="+w.Path);
  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"diagnostico.txt"),report.ToString(),Encoding.UTF8);
  Console.Write(report.ToString());
 }
}
public class GuardContext : ApplicationContext {
 Config config;DateTime configTime;readonly System.Windows.Forms.Timer timer;
 readonly IntentObserver intent=new IntentObserver();readonly FirewallClient firewall=new FirewallClient();
 readonly ElevationGateClient elevation=new ElevationGateClient();
 readonly Native.EventProc callback;GCHandle callbackRoot;readonly List<IntPtr> hooks=new List<IntPtr>();
 readonly Queue<Tuple<uint,IntPtr,uint,uint>> events=new Queue<Tuple<uint,IntPtr,uint,uint>>();
 readonly Dictionary<long,DateTime> fresh=new Dictionary<long,DateTime>();readonly HashSet<long> baseline=new HashSet<long>();
 readonly Dictionary<long,DateTime> cooldown=new Dictionary<long,DateTime>();
 HashSet<int> games=new HashSet<int>();Journal journal;bool active;bool paused;bool stopping;int ticks;
 SettingsState components=new SettingsState();bool toastDenied;bool restorationPending;bool delegatedToasts;
 DateTime nextRestore=DateTime.MinValue;
 IntPtr previousForeground;IntPtr lastGame;DateTime lastGameTime;Process watchdog;
 public GuardContext(Config c) {
  config=c;configTime=File.GetLastWriteTimeUtc(Guard.ConfigFile);intent.Start();
  callback=(hook,ev,h,obj,child,thread,time)=>{if(h!=IntPtr.Zero&&obj==0&&child==0){uint pid;Native.GetWindowThreadProcessId(h,out pid);events.Enqueue(Tuple.Create(ev,h,pid,time));}};
  callbackRoot=GCHandle.Alloc(callback);
  try {
   foreach(uint ev in new uint[]{3,0x8001,0x8002}){var h=Native.SetWinEventHook(ev,ev,IntPtr.Zero,callback,0,0,2);if(h==IntPtr.Zero)throw new Exception("Unable to observe windows.");hooks.Add(h);}
   int id=Process.GetCurrentProcess().Id;long start=Process.GetCurrentProcess().StartTime.ToUniversalTime().Ticks;
   watchdog=Process.Start(new ProcessStartInfo{FileName=Application.ExecutablePath,Arguments="--watchdog "+id+" "+start,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
   if(watchdog==null||watchdog.WaitForExit(100))throw new Exception("Watchdog did not start; protection will not be applied.");
   journal=new Journal{OwnerPid=id,OwnerStart=start};
   foreach(var window in Native.Windows())baseline.Add(window.Handle);
   previousForeground=Native.GetForegroundWindow();
   timer=new System.Windows.Forms.Timer{Interval=50};timer.Tick+=(s,e)=>Tick();timer.Start();
   Guard.Log("START by OverlayApp; waiting for game. General="+c.GeneralWindowGuard+"; no login startup.");
  }catch{Dispose();throw;}
 }
 void Save(){Guard.Write(Guard.StateFile,journal);}
 void Activate() {
  active=true;delegatedToasts=firewall.Installed;
  if((journal.PolicyTouched||journal.FocusTouched)&&!Settings.Restore(journal,new WindowsBackend(),Save,Guard.Log)){
   components=new SettingsState{Focus="previous restoration pending",RestorationPending=true};components.Toasts.Status="previous restoration pending";restorationPending=true;return;
  }
  components=Settings.Apply(journal,config,new WindowsBackend(),Save,Guard.Log,delegatedToasts,toastDenied);
  toastDenied=toastDenied||components.Toasts.AccessDenied;restorationPending=components.RestorationPending;
  if(!journal.Pending&&File.Exists(Guard.StateFile))File.Delete(Guard.StateFile);
  Guard.Log("GAME detected; component status published.");
 }
 void Deactivate(bool stopRouting=false){
  if(journal!=null){
   bool settings=Settings.Restore(journal,new WindowsBackend(),Save,Guard.Log);
   Guard.RestoreWindows(journal,Save,window=>stopRouting||!config.RouteAlways||!window.Moved);
   restorationPending=!settings||journal.Windows.Any(window=>window.RestoreQueued);
   if(!journal.Pending&&File.Exists(Guard.StateFile))File.Delete(Guard.StateFile);
   if(restorationPending)Guard.Log("WARNING restoration pending; journal retained.");
  }
  active=false;lastGame=IntPtr.Zero;
  if(stopRouting||!config.RouteAlways){fresh.Clear();events.Clear();}
 }
 internal static bool SameConfig(Config a,Config b){return a.MuteAppToasts==b.MuteAppToasts&&a.ExtendForegroundTimeout==b.ExtendForegroundTimeout&&a.GeneralWindowGuard==b.GeneralWindowGuard&&a.SuppressFirewallPrompt==b.SuppressFirewallPrompt&&a.BlockInteractiveElevation==b.BlockInteractiveElevation&&a.AlertMonitor==b.AlertMonitor&&a.RouteAlways==b.RouteAlways&&a.UserInputGraceMs==b.UserInputGraceMs&&a.Games.SequenceEqual(b.Games)&&a.KeepVisible.SequenceEqual(b.KeepVisible)&&a.AllowedProcessNames.SequenceEqual(b.AllowedProcessNames)&&a.AllowedExecutablePaths.SequenceEqual(b.AllowedExecutablePaths)&&a.ExactRules.Length==b.ExactRules.Length;}
 internal static bool ReloadConfig(Config before,Config after,Action restoreAll,Action<Config> commit){if(SameConfig(before,after))return false;restoreAll();commit(after);return true;}
 void PublishStatus(){
  bool destination=WindowRouting.MonitorAvailable(config.AlertMonitor??"");
  string toasts=!config.MuteAppToasts?"off":!active?"waiting for game":delegatedToasts?(firewall.Toasts==null?"waiting for administrator helper":firewall.Toasts.Status):components.Toasts.Status;
  bool toastReady=delegatedToasts?firewall.Toasts!=null&&firewall.Toasts.Configured:components.Toasts.Configured;
  string fw=!config.SuppressFirewallPrompt?"off":active?firewall.Status:firewall.Installed?"waiting for game":"administrator setup pending";
  bool degraded=active&&((config.MuteAppToasts&&!toastReady)||(config.ExtendForegroundTimeout&&!components.FocusConfigured)||(config.SuppressFirewallPrompt&&!firewall.Configured));
  bool pending=restorationPending||journal.Windows.Any(w=>w.RestoreQueued)||firewall.RestorationPending||(firewall.Toasts!=null&&firewall.Toasts.RestorationPending)||elevation.Pending;
  Guard.Write(Path.Combine(Guard.Root,"status.json"),new GuardStatus{Mode=paused?"paused":degraded?"degraded":active?"active":config.RouteAlways&&destination?"routing; waiting for game":"waiting for game",Windows=paused?"off":active?"active":"waiting for game",Routing=paused?"off":destination&&(config.RouteAlways||active)?"active, without activating windows":String.IsNullOrEmpty(config.AlertMonitor)?"temporary hiding during game":"destination disconnected",Toasts=toasts,Focus=!config.ExtendForegroundTimeout?"off":active?components.Focus:"waiting for game",Firewall=fw,UAC=elevation.Status,Degraded=degraded,Pending=pending});
 }
 void Tick() {
  try {
   if(File.Exists(Guard.StopFile)||!Guard.HasOwners()){Stop();return;}
   if(watchdog!=null&&watchdog.HasExited){Guard.Log("WATCHDOG unavailable; stopping.");Stop();return;}
   if(ticks++%10==0){
    var modified=File.GetLastWriteTimeUtc(Guard.ConfigFile);if(modified!=configTime){var updated=Guard.Read<Config>(Guard.ConfigFile);updated.Validate();ReloadConfig(config,updated,()=>Deactivate(true),next=>config=next);configTime=modified;}
    bool wasPaused=paused;paused=File.Exists(Guard.PauseFile);if(paused&&!wasPaused)Deactivate(true);
    // Scope is the Overlay Manager lifetime, independent of game detection.
    elevation.Refresh(!paused&&config.BlockInteractiveElevation);
    games.Clear();foreach(var p in Process.GetProcesses())using(p){try{if(p.SessionId==Guard.Session&&Guard.Contains(config.Games,p.ProcessName))games.Add(p.Id);}catch{}}
    bool wanted=games.Count>0&&!paused;if(wanted&&!active)Activate();else if(!wanted&&active)Deactivate();
    if(paused&&journal!=null&&journal.Pending&&DateTime.UtcNow>=nextRestore){nextRestore=DateTime.UtcNow.AddSeconds(5);restorationPending=!Guard.Restore(journal);}
    else if(!active&&journal!=null&&(journal.PolicyTouched||journal.FocusTouched)&&DateTime.UtcNow>=nextRestore){nextRestore=DateTime.UtcNow.AddSeconds(5);restorationPending=!Settings.Restore(journal,new WindowsBackend(),Save,Guard.Log);}
    if(active&&delegatedToasts!=firewall.Installed){Deactivate();Activate();}
    firewall.Refresh(!paused,config.SuppressFirewallPrompt,config.MuteAppToasts&&delegatedToasts);
    PublishStatus();
   }
   bool routing=!paused&&config.RouteAlways&&WindowRouting.MonitorAvailable(config.AlertMonitor??"");
   if(journal.Windows.Any(w=>w.Moved&&!WindowRouting.MonitorAvailable(w.Monitor))){
    foreach(var entry in journal.Windows.Where(w=>w.Moved&&!WindowRouting.MonitorAvailable(w.Monitor)))cooldown[entry.Handle]=DateTime.UtcNow.AddSeconds(10);
    Guard.RestoreWindows(journal,Save,window=>window.Moved&&!WindowRouting.MonitorAvailable(window.Monitor));
   }
   if(journal.Windows.Any(w=>w.RestoreQueued)&&DateTime.UtcNow>=nextRestore){nextRestore=DateTime.UtcNow.AddSeconds(5);Guard.RestoreWindows(journal,Save,window=>window.RestoreQueued);restorationPending=journal.Windows.Any(window=>window.RestoreQueued)||(!active&&(journal.PolicyTouched||journal.FocusTouched));}
   if(!active&&!routing){events.Clear();return;}
   var fg=Native.GetForegroundWindow();var fgw=Native.Info(fg);bool isGame=games.Contains(fgw.Pid);
   intent.GameForeground=isGame;
   // Recover a game foreground immediately, including first tick after activation.
   if(isGame){lastGame=fg;lastGameTime=DateTime.UtcNow;}
   while(events.Count>0) {
    var ev=events.Dequeue();uint age=unchecked((uint)Environment.TickCount-ev.Item4);
    if(ev.Item1==0x8001){long handle=ev.Item2.ToInt64();baseline.Remove(handle);fresh.Remove(handle);cooldown.Remove(handle);if(journal.Windows.RemoveAll(w=>w.Handle==handle)>0)Save();continue;}
    if(age>1000)continue; // never act on stale queued events after a stall.
    uint currentPid;Native.GetWindowThreadProcessId(ev.Item2,out currentPid);if(currentPid!=ev.Item3)continue;
    if(ev.Item1==0x8002&&Native.GetAncestor(ev.Item2,2)==ev.Item2&&!baseline.Contains(ev.Item2.ToInt64())){
     if(Guard.FreshEligible(intent.Age,config.UserInputGraceMs)||(active&&isGame&&elevation.Configured&&!Native.SwitchingShortcuts()))fresh[ev.Item2.ToInt64()]=DateTime.UtcNow;
     else baseline.Add(ev.Item2.ToInt64()); // Never reconsider a deliberately opened window when grace expires.
    }
    if(ev.Item1==3) {
     var w=Native.Info(ev.Item2);bool stole=games.Contains(PidOf(previousForeground))&&!games.Contains(w.Pid)&&ev.Item2==fg;
     if(stole)Guard.Log("GAME_EXIT to "+w.Name+" pid="+w.Pid+" class="+w.Class+" inputAgeMs="+Native.InputAge()+"; source/intent not confirmed.");
     if(games.Contains(w.Pid)){lastGame=ev.Item2;lastGameTime=DateTime.UtcNow;}else if(stole)Consider(w,false,true,false);
     previousForeground=ev.Item2;
    }
   }
   fg=Native.GetForegroundWindow();isGame=games.Contains(PidOf(fg));
   if(!isGame) {if(journal.Windows.Any(window=>!config.RouteAlways||!window.Moved)&&intent.Age<config.UserInputGraceMs){foreach(var w in journal.Windows.Where(window=>!config.RouteAlways||!window.Moved))cooldown[w.Handle]=DateTime.UtcNow.AddSeconds(10);Guard.RestoreWindows(journal,Save,window=>!config.RouteAlways||!window.Moved);}if(!routing)return;}
   foreach(var pair in fresh.ToArray()) {
    if((DateTime.UtcNow-pair.Value).TotalSeconds>3){fresh.Remove(pair.Key);continue;}
    var w=Native.Info(new IntPtr(pair.Key));Consider(w,true,false,isGame);
   }
   if(config.ExactRules.Any(r=>r.Enabled))foreach(var w in Native.Windows())Consider(w,false,false,true);
  }catch(Exception e){Guard.Log("LOOP ERROR: "+e);Stop();}
 }
 int PidOf(IntPtr h){uint p;Native.GetWindowThreadProcessId(h,out p);return (int)p;}
 void Consider(WindowInfo w,bool isFresh,bool stole,bool gameForeground) {
  DateTime until;if(cooldown.TryGetValue(w.Handle,out until)&&until>DateTime.UtcNow)return;
  bool strict=elevation.Configured&&(gameForeground||stole)&&!Native.SwitchingShortcuts();
  var prior=journal.Windows.FirstOrDefault(x=>x.Handle==w.Handle);
  if(prior!=null){
   if(prior.Pid==w.Pid&&prior.Start==w.Start&&(strict||intent.Age>=config.UserInputGraceMs)&&!(strict?Native.SwitchingShortcuts():Native.SwitchingKeys())){
    if(w.Visible&&!prior.Moved&&!prior.RestoreQueued)Native.ShowWindowAsync(new IntPtr(w.Handle),0);
    if(stole&&lastGame!=IntPtr.Zero&&games.Contains(PidOf(lastGame))&&(DateTime.UtcNow-lastGameTime).TotalSeconds<=2)Native.SetForegroundWindow(lastGame);
   }
   return;
  }
  bool exact=config.ExactRules.Any(r=>r.Enabled&&String.Equals(r.Path,w.Path,StringComparison.OrdinalIgnoreCase)&&r.Title==w.Title&&r.Class==w.Class);
  bool popup=w.Class=="#32770"||w.Owned||w.Topmost||Guard.ConsoleWindow(w);
  var plan=Guard.Plan(active,config.GeneralWindowGuard,config.RouteAlways,WindowRouting.MonitorAvailable(config.AlertMonitor??""),gameForeground,isFresh,stole,popup,Guard.SafeCandidate(config,w),intent.Age,config.UserInputGraceMs,strict?false:Native.SwitchingKeys(),exact,strict);
  if(!plan.Suppress&&!plan.Route)return;
  // Validate both target identity and foreground again immediately before the mutation.
  var h=new IntPtr(w.Handle);var current=Native.Info(h);var fg=Native.GetForegroundWindow();
  if(current.Pid!=w.Pid||current.Start!=w.Start||current.Class!=w.Class||!current.Visible||(strict?Native.SwitchingShortcuts():Native.SwitchingKeys())||(!strict&&intent.Age<config.UserInputGraceMs))return;
  if(stole&&(fg!=h||lastGame==IntPtr.Zero||!games.Contains(PidOf(lastGame))||(DateTime.UtcNow-lastGameTime).TotalSeconds>2))return;
  if(!stole&&!games.Contains(PidOf(fg))&&!plan.Route)return;
  var entry=new Hidden{Handle=w.Handle,Pid=w.Pid,Start=w.Start,Class=w.Class,Path=w.Path,Title=w.Title};
  bool move=WindowRouting.Prepare(h,config.AlertMonitor,entry);
  if(!plan.Suppress&&!move)return; // Routing outside game foreground never falls back to hiding.
  journal.Windows.Add(entry);Save();
  bool changed=move?WindowRouting.Move(h,entry):Native.ShowWindowAsync(h,0);
  if(!changed){journal.Windows.Remove(entry);Save();Guard.Log("WARNING window rejected protection: "+w.Name);return;}
  fresh.Remove(w.Handle);Guard.Log((move?"MOVED WITHOUT ACTIVATION":"HIDE queued")+": "+w.Path+" | "+w.Class+" | "+w.Title);
  if(plan.ReturnFocus){bool restored=Native.SetForegroundWindow(lastGame);Guard.Log("RETURN_FOCUS result="+restored+"; Windows may deny the request.");}
 }
 void Stop(){if(stopping)return;stopping=true;if(timer!=null)timer.Stop();Deactivate(true);Guard.Log("STOPPED.");ExitThread();}
 protected override void Dispose(bool disposing){if(journal!=null&&journal.Pending)Guard.Restore(journal);elevation.Dispose();firewall.Dispose();intent.Dispose();foreach(var h in hooks)Native.UnhookWinEvent(h);hooks.Clear();if(callbackRoot.IsAllocated)callbackRoot.Free();if(timer!=null)timer.Dispose();if(watchdog!=null)watchdog.Dispose();base.Dispose(disposing);}
}
public class FakeBackend : SettingsBackend {
 public readonly FakeToastBackend Policy=new FakeToastBackend();
 public bool Exists {get{return Policy.ValueExists;}set{Policy.KeyExists=value;Policy.ValueExists=value;}}
 public int Value {get{return Policy.Value;}set{Policy.Value=value;}}
 public uint Focus=200000;
 public ToastBackend Toasts {get{return Policy;}}
 public uint ReadFocus(){return Focus;}public void WriteFocus(uint v){Focus=v;}
}
public static class Tests {
 static int count;static void Check(bool v,string name){if(!v)throw new Exception("TEST FAILED: "+name);count++;}
 public static void Run(){
  var c=new Config{MuteAppToasts=true,ExtendForegroundTimeout=true,GeneralWindowGuard=true,UserInputGraceMs=2500,Games=new[]{"iRacingSim64DX11","Le Mans Ultimate","acs","acs_x86","AssettoCorsaEVO"},KeepVisible=new string[0]};c.Validate();
  var b=new FakeBackend();var j=new Journal();int saves=0;
  Settings.Apply(j,c,b,()=>saves++,s=>{});Check(b.Exists&&b.Value==1&&b.Focus==Settings.Target&&saves==2,"apply and journal precede effects");
  Settings.Restore(j,b,()=>{},s=>{});Check(!b.Exists&&b.Focus==200000&&!j.Pending,"restore previously absent value");
  b=new FakeBackend{Exists=true,Value=0,Focus=12345};j=new Journal();Settings.Apply(j,c,b,()=>{},s=>{});Settings.Restore(j,b,()=>{},s=>{});Check(b.Exists&&b.Value==0&&b.Focus==12345,"restore existing value");
  b=new FakeBackend();j=new Journal();Settings.Apply(j,c,b,()=>{},s=>{});b.Value=0;b.Focus=42;Settings.Restore(j,b,()=>{},s=>{});Check(b.Value==0&&b.Focus==42,"preserve external changes");
  Check(!Guard.Decide(true,false,true,true,true,true,100,2500,false,true),"recent input takes priority");
  Check(!Guard.Decide(true,false,true,true,true,true,2499,2500,false,true),"boundary before grace period");
  Check(Guard.Decide(true,false,true,true,true,true,2500,2500,false,true),"grace period boundary");
  Check(!Guard.Decide(true,false,true,true,true,true,9999,2500,true,true),"Alt-Tab/modifiers preserved");
  Check(Guard.Decide(true,false,false,true,false,false,9999,2500,false,true),"general focus theft without rule");
  Check(Guard.Decide(true,false,true,false,true,true,9999,2500,false,true),"new general popup without rule");
  Check(!Guard.Decide(true,false,true,false,false,true,9999,2500,false,true),"normal new background window is not a popup");
  Check(!Guard.Decide(true,false,true,false,true,false,9999,2500,false,true),"do not interfere while user is outside the game");
  Check(!Guard.Decide(true,false,true,true,true,true,9999,2500,false,false),"mandatory exclusions");
  Check(!Guard.Decide(false,false,true,true,true,true,9999,2500,false,true),"general mode disabled");
  Check(Guard.Decide(false,true,false,false,false,true,9999,2500,false,true),"optional exact rule");
  foreach(string n in c.Games)Check(Guard.Game(c,new WindowInfo{Name=n}),"detect game "+n);
  Check(!Guard.Game(c,new WindowInfo{Name="iRacingUI"}),"launcher alone does not activate");
  c.AllowedProcessNames=new[]{"AppleMusic","powershell"};c.AllowedExecutablePaths=new[]{"C:\\Allowed\\notes.exe"};
  Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="applemusic",Path="C:\\Apps\\AppleMusic.exe",Pid=123,Start=1}),"allowed process remains visible case-insensitively");
  Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="notes",Path="c:\\allowed\\NOTES.exe",Pid=123,Start=1}),"selected exact executable remains visible");
  Check(Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="notes",Path="C:\\Other\\notes.exe",Pid=123,Start=1}),"same executable filename elsewhere is not a path exception");
  c.AllowedProcessNames=new string[0];c.AllowedExecutablePaths=new string[0];
  var updated=new Config{MuteAppToasts=true,ExtendForegroundTimeout=true,GeneralWindowGuard=true,UserInputGraceMs=2500,Games=c.Games,KeepVisible=c.KeepVisible,AllowedProcessNames=new[]{"AppleMusic"}};updated.Validate();var reloadEffects=new List<string>();
  Check(GuardContext.ReloadConfig(c,updated,()=>reloadEffects.Add("restore all previous windows"),value=>{Check(reloadEffects.SequenceEqual(new[]{"restore all previous windows"}),"previously suppressed/routed windows restore before installing new exceptions");reloadEffects.Add("commit exceptions");}),"adding only an exception triggers active config reload");
  Check(GuardContext.ReloadConfig(updated,c,()=>reloadEffects.Add("restore"),value=>reloadEffects.Add("remove"))&&Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="AppleMusic",Path="C:\\Apps\\AppleMusic.exe",Pid=123,Start=1}),"removing exception reloads and resumes eligibility for future popups");
  Check(!GuardContext.ReloadConfig(c,c,()=>{throw new Exception("unnecessary restore");},value=>{}),"unchanged config does not restore or reload");
  updated.AllowedProcessNames=new string[0];updated.AllowedExecutablePaths=new[]{"C:\\Allowed\\notes.exe"};Check(!GuardContext.SameConfig(c,updated),"exact path exception change also triggers reload");
  foreach(string n in new[]{"OverlayApp","sc-tuner","consent","CredentialUIBroker","WerFault","EasyAntiCheat_EOS","iRacingUI"})Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name=n,Path="C:\\Apps\\x.exe",Pid=123,Start=1}),"preserve "+n);
  Check(Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="system-app",Path=Environment.GetFolderPath(Environment.SpecialFolder.Windows)+"\\a.exe",Pid=123,Start=1}),"ordinary Windows window eligible");
  Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="unknown",Pid=123,Start=1}),"fail closed when path unavailable");
  Check(Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="conhost",Class="ConsoleWindowClass",Path=Environment.GetFolderPath(Environment.SpecialFolder.Windows)+"\\System32\\conhost.exe",Pid=123,Start=1}),"external console can be protected");
  Check(Guard.ConsoleWindow(new WindowInfo{Name="powershell",Class="ConsoleWindowClass"}),"Windows PowerShell recognized");
  Check(Guard.ConsoleWindow(new WindowInfo{Name="pwsh",Class="ConsoleWindowClass"}),"PowerShell 7 recognized");
  Check(Guard.ConsoleWindow(new WindowInfo{Name="WindowsTerminal",Class="CASCADIA_HOSTING_WINDOW_CLASS"}),"Windows Terminal recognized");
  Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,PassThrough=true,Name="custom-overlay",Path="C:\\Apps\\overlay.exe",Pid=123,Start=1}),"pass-through overlay preserved");
  Check(!Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="explorer",Class="Shell_TrayWnd",Path="C:\\Windows\\explorer.exe",Pid=123,Start=1}),"taskbar preserved");
  Check(Guard.SafeCandidate(c,new WindowInfo{Visible=true,Name="explorer",Class="CabinetWClass",Path="C:\\Windows\\explorer.exe",Pid=123,Start=1}),"ordinary Windows dialog eligible");
  Check(IntentObserver.IsSwitchKey(0x12)&&IntentObserver.IsSwitchKey(0x09)&&!IntentObserver.IsSwitchKey(0x57),"Alt-Tab preserved; driving key does not suspend");
  Check(IntentObserver.IsClick(0x201)&&!IntentObserver.IsClick(0x200),"click preserved; mouse movement does not suspend");
  Check(!Guard.FreshEligible(200,2500)&&Guard.FreshEligible(3000,2500),"popup opened by click is not reconsidered after grace period");
  var explorerPlan=Guard.Plan(true,true,true,true,false,true,false,true,true,5000,2500,false);
  Check(explorerPlan.Route&&!explorerPlan.Suppress&&!explorerPlan.ReturnFocus,"game open + Explorer focused: route popup without focusing game");
  var idlePlan=Guard.Plan(false,true,true,true,false,true,false,true,true,5000,2500,false);
  Check(idlePlan.Route&&!idlePlan.ReturnFocus,"no game: always-on routing active");
  Check(!Guard.Plan(true,true,true,true,false,true,false,false,true,5000,2500,false).Route,"normal window outside game focus is not routed");
  Check(!Guard.Plan(true,true,true,true,false,true,false,true,true,100,2500,false).Route,"deliberate click preserves popup outside game");
  Check(!Guard.Plan(true,true,false,true,false,true,false,true,true,5000,2500,false).Route,"redirect_always off leaves Explorer alone");
  Check(!Guard.Plan(true,true,true,false,false,true,false,true,true,5000,2500,false).Route,"missing destination does not send window off screen");
  Check(Guard.Plan(true,true,true,true,true,true,false,true,true,0,2500,false,false,true).Suppress,"confirmed broker gate handles fresh in-game error dialogs during driving input");
  Check(!Guard.Plan(true,true,true,true,false,true,false,true,true,0,2500,false,false,true).Suppress,"strict dialog mode does not act while user is outside game");
  Check(!Guard.Plan(true,true,true,true,true,true,false,true,false,0,2500,false,false,true).Suppress,"strict dialog mode preserves hard security exclusions");
  Check(!Guard.Plan(true,true,true,true,true,true,false,true,true,0,2500,true,false,true).Suppress,"strict dialog mode preserves switch shortcuts");
  var deniedBackend=new FakeBackend();deniedBackend.Policy.DenyProbe=true;j=new Journal();
  var disabledFocus=new Config{MuteAppToasts=true,ExtendForegroundTimeout=false};
  var deniedState=Settings.Apply(j,disabledFocus,deniedBackend,()=>{},message=>{});
  Check(!j.Pending&&!deniedState.RestorationPending&&!deniedState.Toasts.Configured&&deniedState.Toasts.AccessDenied,"unprivileged backend does not leave false Pending");
  j=new Journal{PolicyTouched=true,PolicyExisted=false,PolicyKeyExisted=false};
  Check(Settings.Restore(j,deniedBackend,()=>{},message=>{})&&!j.Pending&&deniedBackend.Policy.Writes==0,"false legacy journal recovered using reads only");
  Check(FirewallClient.EnglishStatus("política aplicada; efeito no Windows a validar")=="policy applied; Windows behavior needs validation","installed v1 toast status is displayed in English");
  Check(FirewallClient.EnglishStatus("não aplicado: UnauthorizedAccessException; restauração pendente")=="not applied: UnauthorizedAccessException; restoration pending","installed v1 error status is displayed in English");
  count+=ToastTests.Run();
  string statusFile=Path.Combine(Path.GetTempPath(),"overlay-uac-status-"+Guid.NewGuid()+".json");
  try{
   foreach(string mode in new[]{"active","degraded","paused","waiting for game"}){
    Guard.Write(statusFile,new GuardStatus{Mode=mode,Degraded=mode=="degraded"});var status=Guard.Read<GuardStatus>(statusFile);
    Check(status.UAC==GuardStatus.UacCoverage&&status.Mode==mode,"UAC exclusion is explicit and independent of "+mode);
   }
  }finally{if(File.Exists(statusFile))File.Delete(statusFile);}
  var fitted=WindowRouting.Fit(new Rectangle(-2500,-1300,3000,2000),new Rectangle(810,-1080,1920,1080));
  Check(fitted==new Rectangle(810,-1080,1920,1080),"alert fits upper display with negative coordinates");
  string f=Path.Combine(Path.GetTempPath(),"corridaguard-test-"+Guid.NewGuid()+".json");try{Guard.Write(f,new Journal{OwnerPid=123,FocusTouched=true,FocusOriginal=200000});Guard.Write(f,new Journal{OwnerPid=456,PolicyTouched=true});var r=Guard.Read<Journal>(f);Check(r.OwnerPid==456&&r.PolicyTouched&&!r.FocusTouched,"atomic journal/serialization");}finally{if(File.Exists(f))File.Delete(f);}
  using(var p=Process.GetCurrentProcess()){long t=p.StartTime.ToUniversalTime().Ticks;Check(Guard.Alive(p.Id,t),"live parent application identity");Check(!Guard.Alive(p.Id,t-1),"reused PID/different start time is not the parent");}
  string locked=Path.Combine(Path.GetTempPath(),"guard-reader-test-"+Guid.NewGuid()+".json");
  try{
   Guard.Write(locked,new GuardStatus{Mode="before"});
   var reader=new FileStream(locked,FileMode.Open,FileAccess.Read,FileShare.Read);
   var release=new Thread(()=>{Thread.Sleep(80);reader.Dispose();});release.Start();
   Guard.Write(locked,new GuardStatus{Mode="after"});release.Join();
   Check(Guard.Read<GuardStatus>(locked).Mode=="after","atomic status write survives a transient non-delete-sharing reader");
  }finally{if(File.Exists(locked))File.Delete(locked);}
  string result=count+" tests passed. Simulated backend; no desktop/registry write API called.";Console.WriteLine(result);File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"testes.txt"),result+Environment.NewLine,Encoding.UTF8);
 }
}
