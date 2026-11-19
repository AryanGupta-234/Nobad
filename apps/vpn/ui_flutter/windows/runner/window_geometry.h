#ifndef RUNNER_WINDOW_GEOMETRY_H_
#define RUNNER_WINDOW_GEOMETRY_H_

// The main window has a designed size, not a full screen: 1180 x 760 by default, at least 960 x 640, at most
// 1440 x 900 (logical pixels), and no maximize. Its last size and position are remembered for this user in
// HKCU\Software\NOBAD\NOBAD VPN\Window and brought back within those limits, on a monitor that is still there.

#include <windows.h>

namespace geometry {

constexpr int kDefaultWidth = 1180, kDefaultHeight = 760;
constexpr int kMinWidth = 960, kMinHeight = 640;
constexpr int kMaxWidth = 1440, kMaxHeight = 900;
constexpr wchar_t kKey[] = L"Software\\NOBAD\\NOBAD VPN\\Window";

inline int Clamp(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

inline double ScaleFor(HWND hwnd) {
  const UINT dpi = hwnd ? GetDpiForWindow(hwnd) : 96;
  return (dpi ? dpi : 96) / 96.0;
}

// Saves the window's rectangle (physical pixels) and the DPI it was taken at.
inline void Save(HWND hwnd) {
  if (IsIconic(hwnd) || IsZoomed(hwnd)) return;
  RECT r{};
  if (!GetWindowRect(hwnd, &r)) return;
  HKEY key;
  if (RegCreateKeyExW(HKEY_CURRENT_USER, kKey, 0, nullptr, 0, KEY_SET_VALUE, nullptr, &key, nullptr) != ERROR_SUCCESS) {
    return;
  }
  const DWORD dpi = GetDpiForWindow(hwnd);
  const DWORD values[5] = {static_cast<DWORD>(r.left), static_cast<DWORD>(r.top),
                           static_cast<DWORD>(r.right - r.left), static_cast<DWORD>(r.bottom - r.top), dpi};
  const wchar_t* names[5] = {L"X", L"Y", L"Width", L"Height", L"Dpi"};
  for (int i = 0; i < 5; i++) {
    RegSetValueExW(key, names[i], 0, REG_DWORD, reinterpret_cast<const BYTE*>(&values[i]), sizeof(DWORD));
  }
  RegCloseKey(key);
}

// Puts the window where it was (clamped to the limits and to a monitor's work area), or centres the default size
// on the monitor it is on. Removes the maximize box.
inline void Restore(HWND hwnd) {
  SetWindowLongPtrW(hwnd, GWL_STYLE, GetWindowLongPtrW(hwnd, GWL_STYLE) & ~static_cast<LONG_PTR>(WS_MAXIMIZEBOX));
  DWORD v[5] = {};
  bool saved = false;
  HKEY key;
  if (RegOpenKeyExW(HKEY_CURRENT_USER, kKey, 0, KEY_QUERY_VALUE, &key) == ERROR_SUCCESS) {
    const wchar_t* names[5] = {L"X", L"Y", L"Width", L"Height", L"Dpi"};
    saved = true;
    for (int i = 0; i < 5; i++) {
      DWORD size = sizeof(DWORD), type = 0;
      if (RegQueryValueExW(key, names[i], nullptr, &type, reinterpret_cast<BYTE*>(&v[i]), &size) != ERROR_SUCCESS ||
          type != REG_DWORD) {
        saved = false;
      }
    }
    RegCloseKey(key);
  }
  RECT want{};
  HMONITOR monitor = nullptr;
  if (saved) {
    want = {static_cast<LONG>(static_cast<int>(v[0])), static_cast<LONG>(static_cast<int>(v[1])),
            static_cast<LONG>(static_cast<int>(v[0]) + static_cast<int>(v[2])),
            static_cast<LONG>(static_cast<int>(v[1]) + static_cast<int>(v[3]))};
    monitor = MonitorFromRect(&want, MONITOR_DEFAULTTONULL);  // a monitor that was unplugged: start fresh
  }
  if (monitor == nullptr) {
    monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY);
    saved = false;
  }
  MONITORINFO info{};
  info.cbSize = sizeof(info);
  if (!GetMonitorInfoW(monitor, &info)) return;
  const RECT& wa = info.rcWork;
  UINT dpi = 96;
  if (HMODULE shcore = LoadLibraryW(L"shcore.dll")) {
    using Fn = HRESULT(WINAPI*)(HMONITOR, int, UINT*, UINT*);
    if (auto f = reinterpret_cast<Fn>(GetProcAddress(shcore, "GetDpiForMonitor"))) {
      UINT x = 96, y = 96;
      if (SUCCEEDED(f(monitor, 0, &x, &y))) dpi = x;
    }
    FreeLibrary(shcore);
  }
  const double s = dpi / 96.0;
  const int maxW = (wa.right - wa.left), maxH = (wa.bottom - wa.top);
  int w = saved ? static_cast<int>(v[2]) : static_cast<int>(kDefaultWidth * s);
  int h = saved ? static_cast<int>(v[3]) : static_cast<int>(kDefaultHeight * s);
  w = Clamp(w, static_cast<int>(kMinWidth * s), static_cast<int>(kMaxWidth * s));
  h = Clamp(h, static_cast<int>(kMinHeight * s), static_cast<int>(kMaxHeight * s));
  w = w > maxW ? maxW : w;
  h = h > maxH ? maxH : h;
  int x = saved ? static_cast<int>(v[0]) : wa.left + (maxW - w) / 2;
  int y = saved ? static_cast<int>(v[1]) : wa.top + (maxH - h) / 2;
  x = Clamp(x, wa.left, wa.right - w);
  y = Clamp(y, wa.top, wa.bottom - h);
  SetWindowPos(hwnd, nullptr, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
}

}  // namespace geometry

#endif  // RUNNER_WINDOW_GEOMETRY_H_
