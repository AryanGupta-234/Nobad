#include "win32_window.h"

#include <dwmapi.h>
#include <flutter_windows.h>

#include <cwchar>

#include "resource.h"

namespace {

/// Window attribute that enables dark mode window decorations.
///
/// Redefined in case the developer's machine has a Windows SDK older than
/// version 10.0.22000.0.
/// See: https://docs.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif

constexpr const wchar_t kWindowClassName[] = L"FLUTTER_RUNNER_WIN32_WINDOW";

/// Registry key for app theme preference.
///
/// A value of 0 indicates apps should use dark mode. A non-zero or missing
/// value indicates apps should use light mode.
constexpr const wchar_t kGetPreferredBrightnessRegKey[] =
  L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
constexpr const wchar_t kGetPreferredBrightnessRegValue[] = L"AppsUseLightTheme";

// The main window's designed size range (logical px, client area): no maximize, no full screen.
constexpr int kMinW = 860, kMinH = 600, kMaxW = 1280, kMaxH = 820;  // 0.8.5: a tighter range
constexpr const wchar_t kPlacementKey[] = L"Software\\NOBAD\\Find\\UIWindow";

// Development runs next to a demo (NOBAD_FIND_UI_ALLOW_SECOND=1) neither read nor write the saved placement.
bool PlacementKept() {
  wchar_t v[4] = {};
  return !(GetEnvironmentVariableW(L"NOBAD_FIND_UI_ALLOW_SECOND", v, 4) > 0 && wcscmp(v, L"1") == 0);
}

UINT DpiFor(HWND hwnd) {
  const UINT dpi = GetDpiForWindow(hwnd);
  return dpi == 0 ? 96 : dpi;
}

// The frame around a client area of this style at this DPI.
SIZE FrameExtra(DWORD style, DWORD ex_style, UINT dpi) {
  RECT r{0, 0, 0, 0};
  AdjustWindowRectExForDpi(&r, style, FALSE, ex_style, dpi);
  return SIZE{r.right - r.left, r.bottom - r.top};
}

int Clamp(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// The saved top-left (physical) and client size (logical), if any.
bool ReadPlacement(int* x, int* y, int* w, int* h) {
  DWORD v[4] = {};
  const wchar_t* names[4] = {L"x", L"y", L"w", L"h"};
  for (int i = 0; i < 4; i++) {
    DWORD size = sizeof(DWORD);
    if (RegGetValueW(HKEY_CURRENT_USER, kPlacementKey, names[i], RRF_RT_REG_DWORD, nullptr, &v[i], &size) !=
        ERROR_SUCCESS) {
      return false;
    }
  }
  *x = static_cast<int>(static_cast<LONG>(v[0]));
  *y = static_cast<int>(static_cast<LONG>(v[1]));
  *w = static_cast<int>(v[2]);
  *h = static_cast<int>(v[3]);
  return *w > 0 && *h > 0;
}

void SavePlacement(HWND hwnd) {
  if (!PlacementKept() || IsIconic(hwnd)) return;
  WINDOWPLACEMENT wp{};
  wp.length = sizeof(wp);
  RECT client{};
  if (!GetWindowPlacement(hwnd, &wp) || !GetClientRect(hwnd, &client)) return;
  const double scale = DpiFor(hwnd) / 96.0;
  const DWORD v[4] = {static_cast<DWORD>(wp.rcNormalPosition.left), static_cast<DWORD>(wp.rcNormalPosition.top),
                      static_cast<DWORD>((client.right - client.left) / scale + 0.5),
                      static_cast<DWORD>((client.bottom - client.top) / scale + 0.5)};
  const wchar_t* names[4] = {L"x", L"y", L"w", L"h"};
  for (int i = 0; i < 4; i++) {
    RegSetKeyValueW(HKEY_CURRENT_USER, kPlacementKey, names[i], REG_DWORD, &v[i], sizeof(DWORD));
  }
}

// The main window's place: where it was last time if that is still on a monitor, else centred on the monitor
// with the mouse; its size in the designed range and inside the monitor's work area (per-monitor DPI).
void PlaceMain(HWND hwnd, int want_w, int want_h, DWORD style, DWORD ex_style) {
  int x = 0, y = 0, w = want_w, h = want_h;
  HMONITOR monitor = nullptr;
  if (PlacementKept() && ReadPlacement(&x, &y, &w, &h)) {
    monitor = MonitorFromPoint(POINT{x + 40, y + 20}, MONITOR_DEFAULTTONULL);
  }
  const bool saved = monitor != nullptr;
  if (!saved) {
    POINT pt{};
    GetCursorPos(&pt);
    monitor = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST);
    w = want_w;
    h = want_h;
  }
  MONITORINFO info{};
  info.cbSize = sizeof(info);
  if (!GetMonitorInfo(monitor, &info)) return;
  const UINT dpi = FlutterDesktopGetDpiForMonitor(monitor);
  const double scale = dpi / 96.0;
  const SIZE extra = FrameExtra(style, ex_style, dpi);
  const RECT& work = info.rcWork;
  const int work_w = work.right - work.left, work_h = work.bottom - work.top;
  int pw = static_cast<int>(Clamp(w, kMinW, kMaxW) * scale + 0.5) + extra.cx;
  int ph = static_cast<int>(Clamp(h, kMinH, kMaxH) * scale + 0.5) + extra.cy;
  if (pw > work_w) pw = work_w;
  if (ph > work_h) ph = work_h;
  if (!saved) {
    x = work.left + (work_w - pw) / 2;
    y = work.top + (work_h - ph) / 2;
  }
  x = Clamp(x, work.left, work.right - pw);
  y = Clamp(y, work.top, work.bottom - ph);
  SetWindowPos(hwnd, nullptr, x, y, pw, ph, SWP_NOZORDER | SWP_NOACTIVATE);
}

// The number of Win32Window objects that currently exist.
static int g_active_window_count = 0;

using EnableNonClientDpiScaling = BOOL __stdcall(HWND hwnd);

// Scale helper to convert logical scaler values to physical using passed in
// scale factor
int Scale(int source, double scale_factor) {
  return static_cast<int>(source * scale_factor);
}

// Dynamically loads the |EnableNonClientDpiScaling| from the User32 module.
// This API is only needed for PerMonitor V1 awareness mode.
void EnableFullDpiSupportIfAvailable(HWND hwnd) {
  HMODULE user32_module = LoadLibraryA("User32.dll");
  if (!user32_module) {
    return;
  }
  auto enable_non_client_dpi_scaling =
      reinterpret_cast<EnableNonClientDpiScaling*>(
          GetProcAddress(user32_module, "EnableNonClientDpiScaling"));
  if (enable_non_client_dpi_scaling != nullptr) {
    enable_non_client_dpi_scaling(hwnd);
  }
  FreeLibrary(user32_module);
}

}  // namespace

// Manages the Win32Window's window class registration.
class WindowClassRegistrar {
 public:
  ~WindowClassRegistrar() = default;

  // Returns the singleton registrar instance.
  static WindowClassRegistrar* GetInstance() {
    if (!instance_) {
      instance_ = new WindowClassRegistrar();
    }
    return instance_;
  }

  // Returns the name of the window class, registering the class if it hasn't
  // previously been registered.
  const wchar_t* GetWindowClass();

  // Unregisters the window class. Should only be called if there are no
  // instances of the window.
  void UnregisterWindowClass();

 private:
  WindowClassRegistrar() = default;

  static WindowClassRegistrar* instance_;

  bool class_registered_ = false;
};

WindowClassRegistrar* WindowClassRegistrar::instance_ = nullptr;

const wchar_t* WindowClassRegistrar::GetWindowClass() {
  if (!class_registered_) {
    WNDCLASS window_class{};
    window_class.hCursor = LoadCursor(nullptr, IDC_ARROW);
    window_class.lpszClassName = kWindowClassName;
    window_class.style = CS_HREDRAW | CS_VREDRAW;
    window_class.cbClsExtra = 0;
    window_class.cbWndExtra = 0;
    window_class.hInstance = GetModuleHandle(nullptr);
    window_class.hIcon =
        LoadIcon(window_class.hInstance, MAKEINTRESOURCE(IDI_APP_ICON));
    window_class.hbrBackground = 0;
    window_class.lpszMenuName = nullptr;
    window_class.lpfnWndProc = Win32Window::WndProc;
    RegisterClass(&window_class);
    class_registered_ = true;
  }
  return kWindowClassName;
}

void WindowClassRegistrar::UnregisterWindowClass() {
  UnregisterClass(kWindowClassName, nullptr);
  class_registered_ = false;
}

Win32Window::Win32Window() {
  ++g_active_window_count;
}

Win32Window::~Win32Window() {
  --g_active_window_count;
  Destroy();
}

bool Win32Window::Create(const std::wstring& title,
                         const Point& origin,
                         const Size& size) {
  Destroy();

  const wchar_t* window_class =
      WindowClassRegistrar::GetInstance()->GetWindowClass();

  const POINT target_point = {static_cast<LONG>(origin.x),
                              static_cast<LONG>(origin.y)};
  HMONITOR monitor = MonitorFromPoint(target_point, MONITOR_DEFAULTTONEAREST);
  UINT dpi = FlutterDesktopGetDpiForMonitor(monitor);
  double scale_factor = dpi / 96.0;

  // The quick find bar is a frameless tool window on top (no taskbar button, no Alt+Tab entry).
  // The main window has no maximize box: it keeps its designed size range (WM_GETMINMAXINFO).
  const DWORD style = popup_ ? WS_POPUP : (WS_OVERLAPPEDWINDOW & ~WS_MAXIMIZEBOX);
  const DWORD ex_style = popup_ ? (WS_EX_TOOLWINDOW | WS_EX_TOPMOST) : 0;
  HWND window = CreateWindowEx(
      ex_style, window_class, title.c_str(), style,
      Scale(origin.x, scale_factor), Scale(origin.y, scale_factor),
      Scale(size.width, scale_factor), Scale(size.height, scale_factor),
      nullptr, nullptr, GetModuleHandle(nullptr), this);

  if (!window) {
    return false;
  }

  UpdateTheme(window);
  if (!popup_) {
    PlaceMain(window, size.width, size.height, style, ex_style);
  }
  if (popup_) {
    const DWORD corner = 2;  // DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND (Windows 11)
    DwmSetWindowAttribute(window, 33, &corner, sizeof(corner));
  }

  return OnCreate();
}

bool Win32Window::Show() {
  if (popup_) {
    const bool shown = ShowWindow(window_handle_, SW_SHOW);
    SetForegroundWindow(window_handle_);
    return shown;
  }
  return ShowWindow(window_handle_, SW_SHOWNORMAL);
}

// static
LRESULT CALLBACK Win32Window::WndProc(HWND const window,
                                      UINT const message,
                                      WPARAM const wparam,
                                      LPARAM const lparam) noexcept {
  if (message == WM_NCCREATE) {
    auto window_struct = reinterpret_cast<CREATESTRUCT*>(lparam);
    SetWindowLongPtr(window, GWLP_USERDATA,
                     reinterpret_cast<LONG_PTR>(window_struct->lpCreateParams));

    auto that = static_cast<Win32Window*>(window_struct->lpCreateParams);
    EnableFullDpiSupportIfAvailable(window);
    that->window_handle_ = window;
  } else if (Win32Window* that = GetThisFromHandle(window)) {
    return that->MessageHandler(window, message, wparam, lparam);
  }

  return DefWindowProc(window, message, wparam, lparam);
}

LRESULT
Win32Window::MessageHandler(HWND hwnd,
                            UINT const message,
                            WPARAM const wparam,
                            LPARAM const lparam) noexcept {
  switch (message) {
    case WM_GETMINMAXINFO: {
      if (popup_) break;
      auto mm = reinterpret_cast<MINMAXINFO*>(lparam);
      const UINT dpi = DpiFor(hwnd);
      const double scale = dpi / 96.0;
      const SIZE extra = FrameExtra(static_cast<DWORD>(GetWindowLongPtr(hwnd, GWL_STYLE)),
                                    static_cast<DWORD>(GetWindowLongPtr(hwnd, GWL_EXSTYLE)), dpi);
      mm->ptMinTrackSize = POINT{static_cast<LONG>(kMinW * scale) + extra.cx, static_cast<LONG>(kMinH * scale) + extra.cy};
      mm->ptMaxTrackSize = POINT{static_cast<LONG>(kMaxW * scale) + extra.cx, static_cast<LONG>(kMaxH * scale) + extra.cy};
      mm->ptMaxSize = mm->ptMaxTrackSize;
      return 0;
    }
    case WM_SYSCOMMAND:
      // no maximize (Win+Up, the system menu, a title-bar double-click)
      if (!popup_ && (wparam & 0xFFF0) == SC_MAXIMIZE) return 0;
      break;
    case WM_NCLBUTTONDBLCLK:
      if (!popup_ && wparam == HTCAPTION) return 0;
      break;
    case WM_EXITSIZEMOVE:
      if (!popup_) SavePlacement(hwnd);
      break;
    case WM_CLOSE:
      if (!popup_) SavePlacement(hwnd);
      break;

    case WM_DESTROY:
      window_handle_ = nullptr;
      Destroy();
      if (quit_on_close_) {
        PostQuitMessage(0);
      }
      return 0;

    case WM_DPICHANGED: {
      auto newRectSize = reinterpret_cast<RECT*>(lparam);
      LONG newWidth = newRectSize->right - newRectSize->left;
      LONG newHeight = newRectSize->bottom - newRectSize->top;

      SetWindowPos(hwnd, nullptr, newRectSize->left, newRectSize->top, newWidth,
                   newHeight, SWP_NOZORDER | SWP_NOACTIVATE);

      return 0;
    }
    case WM_SIZE: {
      // maximized some other way (a program, a snap gesture): back to the designed size
      if (!popup_ && wparam == SIZE_MAXIMIZED) {
        ShowWindow(hwnd, SW_RESTORE);
        return 0;
      }
      RECT rect = GetClientArea();
      if (child_content_ != nullptr) {
        // Size and position the child window.
        MoveWindow(child_content_, rect.left, rect.top, rect.right - rect.left,
                   rect.bottom - rect.top, TRUE);
      }
      return 0;
    }

    case WM_ACTIVATE:
      if (child_content_ != nullptr) {
        SetFocus(child_content_);
      }
      return 0;

    case WM_DWMCOLORIZATIONCOLORCHANGED:
      UpdateTheme(hwnd);
      return 0;
  }

  return DefWindowProc(window_handle_, message, wparam, lparam);
}

void Win32Window::Destroy() {
  OnDestroy();

  if (window_handle_) {
    DestroyWindow(window_handle_);
    window_handle_ = nullptr;
  }
  if (g_active_window_count == 0) {
    WindowClassRegistrar::GetInstance()->UnregisterWindowClass();
  }
}

Win32Window* Win32Window::GetThisFromHandle(HWND const window) noexcept {
  return reinterpret_cast<Win32Window*>(
      GetWindowLongPtr(window, GWLP_USERDATA));
}

void Win32Window::SetChildContent(HWND content) {
  child_content_ = content;
  SetParent(content, window_handle_);
  RECT frame = GetClientArea();

  MoveWindow(content, frame.left, frame.top, frame.right - frame.left,
             frame.bottom - frame.top, true);

  SetFocus(child_content_);
}

RECT Win32Window::GetClientArea() {
  RECT frame;
  GetClientRect(window_handle_, &frame);
  return frame;
}

HWND Win32Window::GetHandle() {
  return window_handle_;
}

void Win32Window::SetQuitOnClose(bool quit_on_close) {
  quit_on_close_ = quit_on_close;
}

bool Win32Window::OnCreate() {
  // No-op; provided for subclasses.
  return true;
}

void Win32Window::OnDestroy() {
  // No-op; provided for subclasses.
}

void Win32Window::UpdateTheme(HWND const window) {
  DWORD light_mode;
  DWORD light_mode_size = sizeof(light_mode);
  LSTATUS result = RegGetValue(HKEY_CURRENT_USER, kGetPreferredBrightnessRegKey,
                               kGetPreferredBrightnessRegValue,
                               RRF_RT_REG_DWORD, nullptr, &light_mode,
                               &light_mode_size);

  (void)result;
  {
    BOOL enable_dark_mode = TRUE;  // NOBAD Find is dark first
    DwmSetWindowAttribute(window, DWMWA_USE_IMMERSIVE_DARK_MODE,
                          &enable_dark_mode, sizeof(enable_dark_mode));
  }
}
