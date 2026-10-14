using System;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public static class WindowRouting {
 [StructLayout(LayoutKind.Sequential)] struct Rect {public int Left,Top,Right,Bottom;}
 [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window,out Rect rect);
 [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr window);
 [DllImport("user32.dll",SetLastError=true)] static extern bool SetWindowPos(IntPtr window,IntPtr after,int x,int y,int width,int height,uint flags);
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct DisplayDevice {
  public int Size;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string Name;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=128)] public string Description;
  public uint Flags;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=128)] public string Id;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=128)] public string Key;
 }
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool EnumDisplayDevices(string name,uint index,ref DisplayDevice device,uint flags);
 static Screen Resolve(string name){
  if(String.IsNullOrEmpty(name))return null;
  foreach(var screen in Screen.AllScreens){
   if(screen.DeviceName.Equals(name,StringComparison.OrdinalIgnoreCase))return screen;
   var device=new DisplayDevice{Size=Marshal.SizeOf(typeof(DisplayDevice))};
   if(EnumDisplayDevices(screen.DeviceName,0,ref device,1)&&String.Equals(device.Id,name,StringComparison.OrdinalIgnoreCase))return screen;
  }
  return null;
 }
 public static bool MonitorAvailable(string name){return Resolve(name)!=null;}
 public static bool Prepare(IntPtr window,string monitor,Hidden entry){
  if(String.IsNullOrEmpty(monitor)||!MonitorAvailable(monitor)||IsZoomed(window))return false;
  Rect r;if(!GetWindowRect(window,out r)||r.Right<=r.Left||r.Bottom<=r.Top)return false;
  entry.Moved=true;entry.Monitor=monitor;entry.Left=r.Left;entry.Top=r.Top;entry.Width=r.Right-r.Left;entry.Height=r.Bottom-r.Top;
  entry.OriginalMonitor=Screen.FromRectangle(new Rectangle(entry.Left,entry.Top,entry.Width,entry.Height)).DeviceName;return true;
 }
 public static Rectangle Fit(Rectangle window,Rectangle work){
  int width=Math.Min(window.Width,work.Width),height=Math.Min(window.Height,work.Height);
  return new Rectangle(Math.Max(work.Left,Math.Min(window.Left,work.Right-width)),Math.Max(work.Top,Math.Min(window.Top,work.Bottom-height)),width,height);
 }
 public static bool Move(IntPtr window,Hidden entry){
  var screen=Resolve(entry.Monitor);
  if(screen==null)return false;var work=screen.WorkingArea;
  var r=Fit(new Rectangle(work.Left+24,work.Top+24,entry.Width,entry.Height),work);
  return SetWindowPos(window,IntPtr.Zero,r.X,r.Y,r.Width,r.Height,0x4014); // ASYNCWINDOWPOS | NOZORDER | NOACTIVATE
 }
 public static bool Restore(IntPtr window,Hidden entry){
  var original=new Rectangle(entry.Left,entry.Top,entry.Width,entry.Height);
  var r=MonitorAvailable(entry.OriginalMonitor??"")?original:Fit(original,Screen.PrimaryScreen.WorkingArea);
  if(!SetWindowPos(window,IntPtr.Zero,r.X,r.Y,r.Width,r.Height,0x4014))return false;
  entry.RestoreQueued=true;System.Threading.Thread.Sleep(50);
  Rect actual;return GetWindowRect(window,out actual)&&actual.Left==r.X&&actual.Top==r.Y&&actual.Right-actual.Left==r.Width&&actual.Bottom-actual.Top==r.Height;
 }
}
