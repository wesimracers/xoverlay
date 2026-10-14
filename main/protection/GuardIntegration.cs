using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Security.Principal;
using System.ServiceProcess;

[DataContract] public class Owner {
 [DataMember] public int Pid; [DataMember] public long Start;
}
[DataContract] public class GuardStatus {
 public const string UacCoverage="not blocked, including administrators";
 [DataMember] public string Mode; [DataMember] public string Firewall; [DataMember] public bool Pending;
 [DataMember] public string Windows; [DataMember] public string Routing; [DataMember] public string Toasts; [DataMember] public string Focus;
 [DataMember] public bool Degraded;
 [DataMember] public string UAC=UacCoverage;
}

public sealed class ElevationGateClient : IDisposable {
 readonly string root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"OverlayElevationGate");
 readonly string sid=WindowsIdentity.GetCurrent().User.Value;
 string lease;DateTime retry=DateTime.MinValue;
 public string Status=GuardStatus.UacCoverage+"; administrator setup pending";
 public bool Configured;public bool Pending;
 public void Refresh(bool enabled){
  Configured=false;Pending=false;
  try{
   string directory=Path.Combine(root,"leases",sid);
   if(!Directory.Exists(directory)){Status=GuardStatus.UacCoverage+"; administrator setup pending";return;}
   using(var self=Process.GetCurrentProcess()){
    lease=Path.Combine(directory,self.Id+".json");
    Guard.Write(lease,new ElevationGateLease{Pid=self.Id,Start=self.StartTime.ToUniversalTime().Ticks,Session=self.SessionId,Enabled=enabled});
   }
   if(DateTime.UtcNow>=retry){retry=DateTime.UtcNow.AddSeconds(10);using(var service=new ServiceController("OverlayElevationGate"))if(service.Status==ServiceControllerStatus.Stopped)service.Start();}
   string statusPath=Path.Combine(root,"status.json");
   if(!File.Exists(statusPath)||(DateTime.UtcNow-File.GetLastWriteTimeUtc(statusPath)).TotalSeconds>5){Status="not blocked; helper status not confirmed";return;}
   var status=Guard.Read<ElevationGateStatus>(statusPath);Configured=enabled&&status.Blocked;Pending=status.Pending;
   Status=!enabled&&!status.Pending&&!status.Blocked?"not blocked; experimental elevation option is off":status.State+(String.IsNullOrEmpty(status.Detail)?"":"; "+status.Detail);
  }catch(Exception error){Status="not confirmed ("+error.GetType().Name+")";}
 }
 public void Dispose(){if(lease!=null)try{File.Delete(lease);}catch{}}
}

// Observe switch shortcuts and clicks, always forwarding the unchanged event.
// Driving keys, wheel input and mouse movement do not suspend protection.
public sealed class IntentObserver : IDisposable {
 delegate IntPtr HookProc(int code,IntPtr message,IntPtr data);
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr SetWindowsHookEx(int type,HookProc proc,IntPtr module,uint thread);
 [DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr hook,int code,IntPtr msg,IntPtr data);
 [DllImport("user32.dll")] static extern bool UnhookWindowsHookEx(IntPtr hook);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandle(string name);
 IntPtr keyboard,mouse;HookProc keyCallback,mouseCallback;uint lastIntent=unchecked((uint)Environment.TickCount);
 public uint Age {get{return unchecked((uint)Environment.TickCount-lastIntent);}}
 public bool GameForeground;
 public static bool IsSwitchKey(int vk){return vk==0x12||vk==0xA4||vk==0xA5||vk==0x11||vk==0xA2||vk==0xA3||vk==0x5B||vk==0x5C||vk==0x09||vk==0x1B;}
 public static bool IsClick(int msg){return msg==0x201||msg==0x204||msg==0x207||msg==0x20B;}
 public void Start(){
  keyCallback=(code,msg,data)=>{if(code>=0&&(!GameForeground||IsSwitchKey(Marshal.ReadInt32(data))))lastIntent=unchecked((uint)Environment.TickCount);return CallNextHookEx(keyboard,code,msg,data);};
  mouseCallback=(code,msg,data)=>{if(code>=0&&IsClick(msg.ToInt32()))lastIntent=unchecked((uint)Environment.TickCount);return CallNextHookEx(mouse,code,msg,data);};
  var module=GetModuleHandle(null);keyboard=SetWindowsHookEx(13,keyCallback,module,0);mouse=SetWindowsHookEx(14,mouseCallback,module,0);
  if(keyboard==IntPtr.Zero||mouse==IntPtr.Zero){Dispose();throw new System.ComponentModel.Win32Exception();}
 }
 public void Dispose(){if(keyboard!=IntPtr.Zero)UnhookWindowsHookEx(keyboard);if(mouse!=IntPtr.Zero)UnhookWindowsHookEx(mouse);keyboard=mouse=IntPtr.Zero;}
}

public sealed class FirewallClient : IDisposable {
 // Translate the persisted status protocol from the already installed v1 helper.
 internal static string EnglishStatus(string value){
  if(value==null)return "not confirmed";
  var legacy=new System.Collections.Generic.Dictionary<string,string>{
   {"pronto; aguardando jogo","ready; waiting for game"},
   {"NotifyOnListen=False confirmado","NotifyOnListen=False confirmed"},
   {"não aplicado; consulte registro","not applied; see log"},
   {"não aplicado; restauração pendente","not applied; restoration pending"},
   {"restauração anterior pendente","previous restoration pending"},
   {"restauração pendente","restoration pending"},
   {"aguardando jogo","waiting for game"},
   {"alteração externa detectada; política não reaplicada","external change detected; policy left unchanged"},
   {"indisponível; consulte registro","unavailable; see log"},
   {"inativo; valores restaurados","inactive; values restored"},
   {"política já definida; efeito no Windows a validar","policy already set; Windows behavior needs validation"},
   {"política aplicada; efeito no Windows a validar","policy applied; Windows behavior needs validation"},
   {"não aplicado: acesso negado; instalar helper administrativo","not applied: access denied; install administrator helper"}
  };
  string translated;if(legacy.TryGetValue(value,out translated))return translated;
  return value.Replace("não aplicado: ","not applied: ").Replace("leitura não confirmada: ","read not confirmed: ").Replace("; restauração pendente","; restoration pending");
 }
 readonly string sid=WindowsIdentity.GetCurrent().User.Value;
 readonly string machineRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"OverlayAppFirewall");
 string lease;DateTime retry=DateTime.MinValue;public string Status="administrator setup pending";
 public bool Installed {get{return Directory.Exists(Path.Combine(machineRoot,"leases",sid));}}
 public bool Configured;public bool RestorationPending;public UserToastStatus Toasts;
 public void Refresh(bool enabled,bool firewallEnabled=false,bool toastEnabled=false){
  try{
   Configured=false;RestorationPending=false;Toasts=null;
   var dir=Path.Combine(machineRoot,"leases",sid);if(!Directory.Exists(dir)){Status="administrator setup pending";return;}
   using(var p=Process.GetCurrentProcess()){
    lease=Path.Combine(dir,p.Id+".json");Guard.Write(lease,new ProtectionLease{Pid=p.Id,Start=p.StartTime.ToUniversalTime().Ticks,Session=p.SessionId,Enabled=enabled,FirewallEnabled=firewallEnabled,ToastEnabled=toastEnabled});
   }
   if(DateTime.UtcNow>=retry){retry=DateTime.UtcNow.AddSeconds(10);using(var service=new ServiceController("OverlayRaceFirewall")){if(service.Status==ServiceControllerStatus.Stopped)service.Start();}}
   var statusPath=Path.Combine(machineRoot,"status.json");
   if(File.Exists(statusPath)&&(DateTime.UtcNow-File.GetLastWriteTimeUtc(statusPath)).TotalSeconds<10){
    var machine=Guard.Read<MachineStatus>(statusPath);Status=EnglishStatus(machine.Firewall);Configured=machine.FirewallConfigured;RestorationPending=machine.RestorationPending;
    Toasts=machine.Toasts.Find(user=>user.SID==sid);
    if(Toasts!=null)Toasts.Status=EnglishStatus(Toasts.Status);
   }else Status="not confirmed";
  }catch(Exception e){Status="unavailable ("+e.GetType().Name+")";}
 }
 public void Dispose(){if(lease!=null)try{File.Delete(lease);}catch{}}
}
